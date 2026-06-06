# backend/api/agent.py
"""Agent API — routes requests through LangGraph / fallback pipeline.

This module ONLY:
- Receives HTTP requests
- Constructs Agent state
- Calls run_agent()
- Returns response

It does NOT:
- Read workspace state files
- Interpret context_ref business meaning
- Force specific intents
- Hardcode business logic
"""

from flask import request, jsonify

from agent.graph import run_agent, get_runtime_status
from backend.core.limits import source_config_too_large
from backend.core.settings import BUILD_COMMIT, TRANSLATOR_ENTRY
from workspace.ids import validate_workspace_id


def handle_agent_status():
    return jsonify(get_runtime_status())


def handle_agent_run():
    """Handle agent run requests.
    
    All business logic (intent routing, context loading, workspace state reading)
    is delegated to the agent pipeline (router → context_loader → ...).
    """
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    intent = (data.get("intent") or "").strip()
    payload = data.get("payload") or {}
    workspace_id = data.get("workspace_id", "default")
    context_ref = data.get("context_ref", "")

    try:
        workspace_id = validate_workspace_id(workspace_id)
    except ValueError:
        return jsonify({"ok": False, "error": "invalid_workspace_id"}), 400
    if source_config_too_large(payload.get("source_config", "")):
        return jsonify({"ok": False, "error": "source_config_too_large"}), 413
    if intent == "translate_config" and not payload.get("source_config") and source_config_too_large(message):
        return jsonify({"ok": False, "error": "source_config_too_large"}), 413

    # Build unified payload — context_ref goes into the agent pipeline
    effective_payload = dict(payload)
    if context_ref:
        effective_payload["context_ref"] = context_ref

    user_input = message or payload.get("source_config", "")
    if not intent and not user_input:
        return jsonify({
            "ok": False,
            "error": "Either 'message' or 'intent'+'payload' is required",
        }), 400

    result = run_agent(
        user_input=user_input,
        intent=intent,
        payload=effective_payload,
        workspace_id=workspace_id,
    )

    return jsonify({
        **result,
        "build_commit": BUILD_COMMIT,
        "translator_entry": TRANSLATOR_ENTRY,
    })
