# backend/api/agent_routes.py
"""Agent API routes — v2.1.1 unified entry point."""

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


def _infer_compat_intent(message: str, payload: dict, explicit: str, context_ref: str) -> str:
    if explicit:
        return explicit
    if context_ref:
        return ""
    if isinstance(payload, dict) and (
        payload.get("source_config") or payload.get("source_vendor") or payload.get("target_vendor")
    ):
        return "translate_config"
    try:
        from agent.legacy.intent_router import _infer
        inferred = _infer(message or "")
        return inferred if inferred != "assistant_chat" else ""
    except Exception:
        return ""


def _result_status(result: dict) -> int:
    error = result.get("error")
    if error == "source_config_too_large":
        return 413
    if error == "invalid_workspace_id":
        return 400
    return 200


def _normalize_compat_result(result: dict, ws_id: str) -> dict:
    """Backfill stable v2.1.1 message fields without exposing unsafe payloads."""
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
    result.setdefault("llm", {"enabled": False, "used": False})
    if result.get("trace_id") and not result.get("trace_available"):
        result["trace_available"] = True
    return result


def agent_message():
    """POST /api/agent/message — submit user message via AgentApp."""
    data = request.get_json(silent=True) or {}
    user_input = data.get("message", data.get("text", ""))

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
    if data.get("intent") == "translate_config" and source_config_too_large(str(user_input)):
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
        compat_payload = dict(payload)
        context_ref = data.get("context_ref") or metadata.get("context_ref") or ""
        if context_ref:
            compat_payload["context_ref"] = context_ref
        intent = _infer_compat_intent(
            user_input,
            compat_payload,
            data.get("intent") or metadata.get("intent") or "",
            context_ref,
        )
        if compat_payload or data.get("intent") or context_ref or intent:
            from agent.legacy.graph import run_agent
            result_payload = run_agent(
                user_input=user_input,
                intent=intent,
                payload=compat_payload,
                workspace_id=ws_id,
                session_id=session_id or "",
            )
            result_payload = _normalize_compat_result(result_payload, ws_id)
            if result_payload.get("final_response"):
                from agent.llm.runtime import sanitize_provider_output
                result_payload["final_response"], stripped = sanitize_provider_output(result_payload["final_response"])
                if stripped:
                    result_payload.setdefault("metadata", {})["reasoning_stripped"] = True
            return jsonify(result_payload), _result_status(result_payload)

        from agent.app.service import get_default_agent_app
        app = get_default_agent_app()
        result = app.submit_user_message(
            user_input=user_input,
            session_id=session_id,
            workspace_id=ws_id,
            metadata=metadata,
        )
        payload = result.to_dict()
        payload = _normalize_compat_result(payload, ws_id)
        if payload.get("final_response"):
            from agent.llm.runtime import sanitize_provider_output
            payload["final_response"], stripped = sanitize_provider_output(payload["final_response"])
            if stripped:
                payload.setdefault("metadata", {})["reasoning_stripped"] = True
        return jsonify(payload)
    except Exception as e:
        _log.exception("agent_message failed")
        return server_error("agent execution failed")
