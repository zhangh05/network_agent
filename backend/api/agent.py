# backend/api/agent.py
"""Agent API — routes requests through LangGraph / fallback pipeline."""

from flask import request, jsonify

from agent.graph import run_agent, get_runtime_status
from backend.core.settings import BUILD_COMMIT, TRANSLATOR_ENTRY


def handle_agent_status():
    """GET /api/agent/status"""
    return jsonify(get_runtime_status())


def handle_agent_run():
    """POST /api/agent/run"""
    data = request.get_json(silent=True) or {}

    # Support both message + payload and explicit intent modes
    message = (data.get("message") or "").strip()
    intent = (data.get("intent") or "").strip()
    payload = data.get("payload") or {}
    workspace_id = data.get("workspace_id", "default")

    # Merge: if no explicit intent but has message, use message as user_input
    user_input = message or payload.get("source_config", "")
    if not intent and not user_input:
        return jsonify({
            "ok": False,
            "error": "Either 'message' or 'intent'+'payload' is required",
        }), 400

    # Run agent pipeline
    result = run_agent(
        user_input=user_input,
        intent=intent,
        payload=payload,
        workspace_id=workspace_id,
    )

    return jsonify({
        **result,
        "build_commit": BUILD_COMMIT,
        "translator_entry": TRANSLATOR_ENTRY,
    })
