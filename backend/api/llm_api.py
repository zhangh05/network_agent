# backend/api/llm_api.py
"""LLM API endpoints — status, test, config CRUD."""

from flask import request, jsonify
from agent.llm.client import LLMClient
from agent.llm.settings import (
    load_llm_settings, save_llm_settings, delete_llm_settings,
    sanitize_llm_settings, validate_llm_settings,
)
from agent.state import NetworkAgentState


def handle_llm_status():
    from agent.llm.runtime import get_llm_status
    status = get_llm_status()
    settings = load_llm_settings()
    status["settings_file_exists"] = settings is not None
    status["enabled_by_ui"] = settings.get("enabled", False) if settings else None
    if settings:
        status["key_configured"] = bool(settings.get("api_key"))
        status["key_preview"] = sanitize_llm_settings(settings).get("key_preview")
        status["config_source"] = "ui_settings" if status["settings_file_exists"] else status.get("config_source", "default")
    return jsonify(status)


def handle_llm_config_get():
    settings = load_llm_settings()
    if settings:
        return jsonify(sanitize_llm_settings(settings))
    return jsonify({"enabled": False, "provider": "disabled"})


def handle_llm_config_post():
    data = request.get_json(silent=True) or {}
    errors = validate_llm_settings(data)
    if errors:
        return jsonify({"ok": False, "errors": errors}), 400
    settings = save_llm_settings(data)
    return jsonify({"ok": True, "config": sanitize_llm_settings(settings)})


def handle_llm_config_delete():
    ok = delete_llm_settings()
    return jsonify({"ok": True, "deleted": ok})


def handle_llm_test():
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
