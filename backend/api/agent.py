# backend/api/agent.py
"""Agent API — routes requests through LangGraph / fallback pipeline."""

import json
import os
from flask import request, jsonify

from agent.graph import run_agent, get_runtime_status
from backend.core.settings import BUILD_COMMIT, TRANSLATOR_ENTRY


def handle_agent_status():
    return jsonify(get_runtime_status())


def handle_agent_run():
    """Handle agent run requests. context_ref is passed through to context_loader."""
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    intent = (data.get("intent") or "").strip()
    payload = data.get("payload") or {}
    workspace_id = data.get("workspace_id", "default")
    context_ref = data.get("context_ref", "")

    # Context QA: follow-up on last result
    # Route as context_qa intent — context_loader handles workspace state loading
    if context_ref == "last_result":
        # Run through normal agent pipeline with context_qa intent
        # The context_loader node handles context_ref=last_result
        result = run_agent(
            user_input=message,
            intent="context_qa",
            payload={"question": message, "context_ref": "last_result"},
            workspace_id=workspace_id,
        )
        return jsonify({
            **result,
            "build_commit": BUILD_COMMIT,
            "translator_entry": TRANSLATOR_ENTRY,
        })

    # Normal agent run
    user_input = message or payload.get("source_config", "")
    if not intent and not user_input:
        return jsonify({
            "ok": False,
            "error": "Either 'message' or 'intent'+'payload' is required",
        }), 400

    # Pass context_ref through for context_loader
    effective_payload = dict(payload)
    if context_ref:
        effective_payload["context_ref"] = context_ref

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
