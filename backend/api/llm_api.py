# backend/api/llm_api.py
"""LLM-specific API endpoints — /api/agent/llm/status, /api/agent/llm/test."""

from flask import request, jsonify
from agent.llm.client import LLMClient
from agent.state import NetworkAgentState


def handle_llm_status():
    """GET /api/agent/llm/status"""
    return jsonify(LLMClient.status())


def handle_llm_test():
    """POST /api/agent/llm/test"""
    data = request.get_json(silent=True) or {}
    task = data.get("task", "result_summarize")
    message = data.get("message", "")

    if task not in ("result_summarize", "context_qa", "response_compose"):
        return jsonify({"ok": False, "error": f"disallowed test task: {task}"}), 400

    state = NetworkAgentState(
        intent="translate_config",
        tool_results={"ok": True, "deployable_config": "test", "manual_review": [], "unsupported": [], "audit": {}},
    )

    client = LLMClient()
    output = client.generate(task, state, user_question=message)

    return jsonify({
        "ok": output.llm_used,
        "provider": client.provider_info().get("provider"),
        "model": client.provider_info().get("model"),
        "llm_used": output.llm_used,
        "policy_pass": output.policy_decision.allowed if output.policy_decision else False,
        "response": output.answer if output.safe_to_show else "[blocked by policy]",
        "fallback_reason": output.fallback_reason,
    })
