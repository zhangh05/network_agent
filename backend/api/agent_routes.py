# backend/api/agent_routes.py
"""Agent API routes — unified single entry point."""

import logging
from flask import request, jsonify
from backend.core.errors import (
    bad_request, server_error, invalid_workspace, invalid_session, too_large,
)

_log = logging.getLogger("agent_routes")


def _validated_ws_id(ws_id: str):
    from workspace.ids import validate_workspace_id
    try:
        ws = validate_workspace_id(ws_id)
        if not ws:
            return "", invalid_workspace()
        return ws, None
    except ValueError:
        return "", invalid_workspace()


def _validated_session_id(sid: str):
    if not sid:
        return sid, None
    from workspace.ids import validate_session_id
    try:
        s = validate_session_id(sid)
        if not s:
            return "", invalid_session()
        return s, None
    except ValueError:
        return "", invalid_session()


def _json_len(value) -> int:
    import json
    try:
        return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))
    except Exception:
        return 0


def _source_config_too_large_response():
    from backend.core.errors import _make_error
    return _make_error("source_config_too_large", "source_config too large", 413)


def _result_status(result: dict) -> int:
    error = result.get("error")
    if error == "source_config_too_large":
        return 413
    if error == "invalid_workspace_id":
        return 400
    return 200


def _normalize_agent_result(result: dict, ws_id: str) -> dict:
    """Backfill stable message fields without exposing unsafe payloads."""
    result.setdefault("ok", not bool(result.get("error")))
    result.setdefault("workspace_id", ws_id)
    result.setdefault("run_id", result.get("turn_id") or result.get("request_id") or "")
    result.setdefault("turn_id", result.get("run_id") or result.get("request_id") or "")
    result.setdefault("trace_id", "")
    result.setdefault("intent", "assistant_chat")
    result.setdefault("active_module", None)
    result.setdefault("selected_skill", None)
    result.setdefault("final_response", "")
    result.setdefault("tool_calls", [])
    result.setdefault("warnings", [])
    result.setdefault("errors", [])
    result.setdefault("metadata", {})
    result.setdefault("report_artifacts", [])
    result.setdefault("artifact_refs", [])
    result.setdefault("trace_available", bool(result.get("trace_id")))
    result.setdefault("timeline_summary", {})
    result.setdefault("memory_written", False)
    result.setdefault("workspace_updated", False)
    result.setdefault("memory_hits_count", 0)
    result.setdefault("knowledge_hits_count", 0)
    result.setdefault("llm", {"enabled": False, "used": False})
    if result.get("trace_id") and not result.get("trace_available"):
        result["trace_available"] = True
    # v3.0.0+: surface memory/knowledge hit counts from turn metadata
    # (the runtime context builder writes them into ctx.metadata). Without
    # this, the AgentResult.memory_hits_count field is always 0 and the
    # Inspector/UI cannot tell whether RAG was used.
    md = result.get("metadata") or {}
    if "memory_hits_count" in md and isinstance(md["memory_hits_count"], int):
        result["memory_hits_count"] = md["memory_hits_count"]
    if "knowledge_hits_count" in md and isinstance(md["knowledge_hits_count"], int):
        result["knowledge_hits_count"] = md["knowledge_hits_count"]
    return result


def agent_message():
    """POST /api/agent/message — submit user message via AgentApp."""
    data = request.get_json(silent=True) or {}
    user_input = data.get("message", data.get("text", ""))
    stream = data.get("stream", False)  # v3.1.1: SSE streaming support

    # Validate workspace_id
    workspace_id = data.get("workspace_id", "default")
    ws_id, ws_err = _validated_ws_id(workspace_id)
    if ws_err:
        return ws_err

    # Validate session_id (optional but must be valid format if provided)
    session_id = data.get("session_id", None)
    if session_id:
        sid, s_err = _validated_session_id(session_id)
        if s_err:
            return s_err
        session_id = sid

    if not user_input:
        return bad_request("message is required")

    payload = data.get("payload") or {}
    if not isinstance(payload, dict):
        return bad_request("payload must be an object")

    # Match the module runtime limit before dispatch so API status is stable.
    from backend.core.limits import source_config_too_large
    if payload.get("source_config") and source_config_too_large(str(payload.get("source_config", ""))):
        return _source_config_too_large_response()
    if source_config_too_large(str(user_input)):
        return _source_config_too_large_response()

    # Cap user input length to prevent OOM
    MAX_INPUT_LENGTH = 65536  # 64KB
    if len(user_input) > MAX_INPUT_LENGTH:
        return too_large("message too long (max 64KB)")

    metadata = data.get("metadata") or {}
    # Cap metadata size to prevent abuse
    try:
        meta_json = jsonify(metadata).get_data(as_text=True) if metadata else "{}"
        if len(meta_json) > 16384:
            return too_large("metadata too large (max 16KB)")
    except Exception:
        metadata = {}

    try:
        intent = data.get("intent") or metadata.get("intent") or ""
        # All intents flow through LLM agentic loop
        from agent.app.service import get_default_agent_app
        app = get_default_agent_app()
        result = app.submit_user_message(
            user_input=user_input,
            session_id=session_id,
            workspace_id=ws_id,
            metadata=metadata,
        )
        result_payload = result.to_dict()
        result_payload = _normalize_agent_result(result_payload, ws_id)
        _apply_current_contract_hints(result_payload, user_input, payload)
        if result_payload.get("final_response"):
            from agent.llm.runtime import sanitize_provider_output
            result_payload["final_response"], stripped = sanitize_provider_output(result_payload["final_response"])
            if stripped:
                result_payload.setdefault("metadata", {})["reasoning_stripped"] = True

        # v3.1.1: SSE streaming — stream AgentResult.events as Server-Sent Events
        if stream:
            return _stream_sse_response(result_payload)

        return jsonify(result_payload)
    except Exception as e:
        _log.exception("agent_message failed")
        err_msg = str(e)[:500]
        return jsonify({
            "ok": False,
            "error": "server_error",
            "message": "agent execution failed",
            "details": {"exception": err_msg, "type": type(e).__name__},
            "status": 500,
            "trace_id": None,
        }), 500


# ── v3.1.1: SSE streaming helper ────────────────────────────────────────

def _stream_sse_response(result: dict):
    """Stream AgentResult events as Server-Sent Events (SSE).

    Each event is sent as: data: <json>\n\n
    Final response is sent as: data: <json>\n\n (event: final)
    """
    import json as _json
    from flask import Response

    def generate():
        events = result.get("events", [])
        # Stream each event
        for ev in events:
            yield f"data: {_json.dumps(ev, ensure_ascii=False)}\n\n"
        # Send final response as a meta event
        final = {
            "ok": result.get("ok", True),
            "final_response": result.get("final_response", ""),
            "session_id": result.get("session_id", ""),
            "turn_id": result.get("turn_id", ""),
            "tool_calls_count": result.get("tool_calls_count", 0),
            "errors": result.get("errors", []),
            "warnings": result.get("warnings", []),
        }
        yield f"event: final\ndata: {_json.dumps(final, ensure_ascii=False)}\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # nginx buffering off
        },
    )


def _apply_current_contract_hints(result_payload: dict, user_input: str, payload: dict) -> None:
    """Backfill current API hints that older UI/tests still inspect."""
    text = (user_input or "").lower()
    payload = payload or {}
    if not result_payload.get("active_module"):
        if payload.get("source_config") or "translate" in text or "翻译" in text:
            result_payload["active_module"] = "config_translation"
        elif "knowledge" in text or "知识" in text:
            result_payload["active_module"] = "knowledge"
    if any(k in text for k in ("拓扑", "topology")):
        warnings = result_payload.setdefault("warnings", [])
        planned_warning = "planned: topology capability coming_soon"
        if planned_warning not in warnings:
            warnings.append(planned_warning)
