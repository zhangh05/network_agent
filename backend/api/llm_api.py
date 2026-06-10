# backend/api/llm_api.py
"""LLM API endpoints — status, test, config CRUD.

LLM configuration is GLOBAL — it does NOT vary by workspace or session.
The config is stored in a single file: config/LLM_setting.json
Workspace-specific LLM config is intentionally not supported.
"""

from flask import request, jsonify
from agent.llm.client import LLMClient
from agent.llm.settings import (
    load_llm_settings, save_llm_settings, delete_llm_settings,
    sanitize_llm_settings, validate_llm_settings,
    resolve_effective_llm_config,
    get_llm_setting_path,
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
    # LLM config is global — reject any attempt to scope by workspace
    if request.args.get("workspace_id"):
        return jsonify({
            "ok": False,
            "error": "LLM config is global and does not accept workspace_id parameter. "
                     "Configuration is stored in config/LLM_setting.json and applies to all workspaces."
        }), 400
    settings = load_llm_settings()
    if settings:
        result = sanitize_llm_settings(settings)
        result["config_path"] = get_llm_setting_path()
        result["global"] = True
        return jsonify(result)
    return jsonify({
        "enabled": False, "provider": "disabled",
        "config_path": get_llm_setting_path(),
        "global": True,
        "note": "No UI settings saved yet. Use POST /api/agent/llm/config to configure. "
                "Configuration is global — one setting for all workspaces."
    })


def handle_llm_config_post():
    data = request.get_json(silent=True) or {}
    # LLM config is global — reject workspace_id
    if data.get("workspace_id"):
        return jsonify({
            "ok": False,
            "error": "LLM config is global and does not accept workspace_id. "
                     "Configuration applies to all workspaces."
        }), 400
    errors = validate_llm_settings(data)
    if errors:
        return jsonify({"ok": False, "errors": errors}), 400
    settings = save_llm_settings(data)
    result = sanitize_llm_settings(settings)
    result["config_path"] = get_llm_setting_path()
    result["global"] = True
    return jsonify({"ok": True, "config": result})


def handle_llm_config_delete():
    ok = delete_llm_settings()
    return jsonify({"ok": True, "deleted": ok})


def handle_llm_test():
    """Test LLM connectivity — uses UI settings as highest priority."""
    data = request.get_json(silent=True) or {}
    task = data.get("task", "result_summarize")
    message = data.get("message", "")

    if task not in ("result_summarize", "context_qa", "response_compose"):
        return jsonify({"ok": False, "error": f"disallowed test task: {task}"}), 400

    # Use unified effective config for test
    cfg = resolve_effective_llm_config()
    if not cfg.get("enabled"):
        return jsonify({
            "ok": False,
            "llm_used": False,
            "config_source": cfg.get("config_source", "default"),
            "enabled_by_ui": cfg.get("enabled_by_ui"),
            "provider": "disabled",
            "model": "",
            "fallback_reason": "disabled",
            "message": "LLM is disabled. Enable it via System Settings.",
        })

    state = NetworkAgentState(
        intent="translate_config",
        tool_results={
            "ok": True, "deployable_config": "test",
            "manual_review": [], "unsupported": [], "audit": {},
        },
    )
    client = LLMClient()
    output = client.generate(task, state, user_question=message)

    return jsonify({
        "ok": output.llm_used,
        "provider": client.provider_info().get("provider"),
        "model": client.provider_info().get("model"),
        "llm_used": output.llm_used,
        "config_source": cfg.get("config_source", "default"),
        "policy_pass": output.policy_decision.allowed if output.policy_decision else True,
        "response": output.answer,  # Always return answer, non-blocking
        "safe_to_show": output.safe_to_show,
        "fallback_reason": output.fallback_reason,
        "warnings": output.warnings,
        "metadata": output.metadata if hasattr(output, "metadata") else {},
    })
