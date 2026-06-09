# backend/api/sse.py
"""Server-Sent Events (SSE) streaming for Agent pipeline.

Provides a streaming alternative to the synchronous /api/agent/run endpoint.
When the client sends stream=true, the server emits SSE events as each
pipeline node completes, rather than waiting for the full pipeline to finish.

Usage:
  POST /api/agent/run  {"message": "...", "stream": true}

SSE event types:
  - node_progress: emitted after each pipeline node completes
  - pipeline_done: emitted once with the full result
  - pipeline_error: emitted on unrecoverable error
"""

import json
import time
import threading
from flask import request, Response, jsonify


def handle_agent_run_sse():
    """Handle agent run with SSE streaming.

    Reuses the same pipeline as handle_agent_run, but wraps it in
    a thread and emits node completion events as they happen.
    """
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    intent = (data.get("intent") or "").strip()
    payload = data.get("payload") or {}
    workspace_id = data.get("workspace_id", "default")
    session_id = (data.get("session_id") or "").strip()
    context_ref = data.get("context_ref", "")

    # Validation
    from workspace.ids import validate_workspace_id, validate_session_id
    try:
        workspace_id = validate_workspace_id(workspace_id)
    except ValueError:
        return jsonify({"ok": False, "error": "invalid_workspace_id"}), 400
    if session_id:
        try:
            session_id = validate_session_id(session_id)
        except ValueError:
            return jsonify({"ok": False, "error": "invalid_session_id"}), 400
    from backend.core.limits import source_config_too_large
    if source_config_too_large(payload.get("source_config", "")):
        return jsonify({"ok": False, "error": "source_config_too_large"}), 413

    effective_payload = dict(payload)
    if context_ref:
        effective_payload["context_ref"] = context_ref
    user_input = message or payload.get("source_config", "")
    if not intent and not user_input:
        return jsonify({"ok": False, "error": "Either 'message' or 'intent'+'payload' is required"}), 400

    # Shared state for thread communication
    result_holder = {"result": None, "error": None}
    done_event = threading.Event()

    # TODO(v2): To support true per-node streaming, agent/graph.py needs an
    # observer/hook mechanism that emits events between nodes. Currently the
    # pipeline is synchronous so we can only send node_progress after completion.

    def _run_pipeline():
        """Run the agent pipeline in a background thread."""
        try:
            from agent.graph import run_agent
            result = run_agent(
                user_input=user_input,
                intent=intent,
                payload=effective_payload,
                workspace_id=workspace_id,
                session_id=session_id,
            )
            result_holder["result"] = result
        except Exception as e:
            result_holder["error"] = str(e)[:500]
        finally:
            done_event.set()

    # Start pipeline in background thread
    thread = threading.Thread(target=_run_pipeline, daemon=True)
    thread.start()

    def _event_stream():
        """Generate SSE events."""
        # Send initial event
        yield _format_sse("pipeline_start", {
            "run_id": f"run_{int(time.time())}",
            "message": "Pipeline started",
            "nodes": ["router", "context_loader", "planner", "executor",
                      "verifier", "composer", "memory_writer"],
        })

        # Wait for pipeline completion
        while not done_event.is_set():
            done_event.wait(timeout=1.0)
            # Send heartbeat to keep connection alive
            yield _format_sse("heartbeat", {"ts": int(time.time())})

        # Pipeline finished — send all node events + final result
        if result_holder["error"]:
            yield _format_sse("pipeline_error", {
                "error": result_holder["error"],
            })
        elif result_holder["result"]:
            result = result_holder["result"]

            # Send node progress events from timeline
            timeline = result.get("timeline_summary", {})
            node_events_data = timeline.get("nodes", [])
            for i, node_data in enumerate(node_events_data):
                yield _format_sse("node_progress", {
                    "node": node_data.get("name", f"node_{i}"),
                    "status": node_data.get("status", "success"),
                    "duration_ms": node_data.get("duration_ms", 0),
                    "progress": f"{i + 1}/{len(node_events_data)}",
                })

            # Send final result
            yield _format_sse("pipeline_done", {
                    "ok": result.get("ok", False),
                    "status": result.get("status", ""),
                    "intent": result.get("intent", ""),
                    "active_module": result.get("active_module", ""),
                    "final_response": result.get("final_response", ""),
                    "run_id": result.get("run_id", ""),
                    "runtime_mode": result.get("runtime_mode", ""),
                    "memory_written": result.get("memory_written", False),
                    "ui_actions": result.get("ui_actions", []),
                    "artifact_refs": result.get("artifact_refs", []),
                    "warnings": result.get("warnings", []),
                    "verification": result.get("verification", {}),
                    "quality_summary": result.get("quality_summary", {}),
                    "llm": result.get("llm", {}),
                })
        # else: both result and error are None — shouldn't happen

    return Response(
        _event_stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _format_sse(event_type: str, data: dict) -> str:
    """Format an SSE message."""
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
