# backend/api/agent.py
"""Agent API — routes requests through LangGraph / fallback pipeline."""

import json, os
from flask import request, jsonify

from agent.graph import run_agent, get_runtime_status
from backend.core.settings import BUILD_COMMIT, TRANSLATOR_ENTRY


def handle_agent_status():
    return jsonify(get_runtime_status())


def handle_agent_run():
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    intent = (data.get("intent") or "").strip()
    payload = data.get("payload") or {}
    workspace_id = data.get("workspace_id", "default")
    context_ref = data.get("context_ref", "")

    # Context QA: follow-up question on last result
    if context_ref == "last_result":
        return _handle_context_qa(message, workspace_id)

    # Normal agent run
    user_input = message or payload.get("source_config", "")
    if not intent and not user_input:
        return jsonify({"ok": False, "error": "Either 'message' or 'intent'+'payload' is required"}), 400

    result = run_agent(user_input=user_input, intent=intent, payload=payload, workspace_id=workspace_id)

    return jsonify({**result, "build_commit": BUILD_COMMIT, "translator_entry": TRANSLATOR_ENTRY})


def _handle_context_qa(message, workspace_id):
    """Handle follow-up question based on last workspace state."""
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ws_path = os.path.join(root, "workspaces", workspace_id or "default", "state.json")

    if not os.path.isfile(ws_path):
        return jsonify({"ok": True, "intent": "context_qa", "final_response":
            "当前没有可解释的翻译结果，请先执行一次配置翻译。", "llm": {"enabled": False, "used": False}})

    try:
        with open(ws_path, encoding="utf-8") as f:
            ws = json.load(f)
    except Exception:
        return jsonify({"ok": True, "intent": "context_qa", "final_response": "无法读取上次结果。"})

    if not ws.get("last_intent"):
        return jsonify({"ok": True, "intent": "context_qa", "final_response": "当前没有可解释的翻译结果。"})

    # Use workspace summary as payload for context_qa
    result = run_agent(
        user_input=message,
        intent="context_qa",
        payload={"workspace_summary": ws, "question": message},
        workspace_id=workspace_id,
    )
    return jsonify({**result, "build_commit": BUILD_COMMIT, "translator_entry": TRANSLATOR_ENTRY})
