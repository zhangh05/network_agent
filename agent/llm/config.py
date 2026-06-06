# agent/llm/config.py
"""LLM config loader — unified config with priority: env > llm.local.yaml > llm.yaml."""

import os
import yaml
from pathlib import Path
from typing import Any, Dict, Optional

from agent.llm.key_resolver import resolve_api_key, get_key_source, is_key_loaded, mask_secret

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config"


def load_llm_config() -> dict:
    """Load LLM config with priority: env override > llm.local.yaml > llm.yaml > fallback defaults."""
    config = _default_config()

    # 1. Base config/llm.yaml
    base_path = CONFIG_DIR / "llm.yaml"
    if base_path.is_file():
        _merge(config, _load_yaml(str(base_path)))

    # 2. Override with config/llm.local.yaml (ignored by git)
    local_path = CONFIG_DIR / "llm.local.yaml"
    if local_path.is_file():
        _merge(config, _load_yaml(str(local_path)))

    # 3. Env overrides
    _apply_env_overrides(config)

    return config


def resolve_provider_config(llm_config: dict = None) -> dict:
    """Get the active provider config with resolved API key."""
    if llm_config is None:
        llm_config = load_llm_config()

    default = llm_config.get("default_provider", "disabled")
    providers = llm_config.get("providers", {})

    result = {
        "enabled": llm_config.get("enabled", False),
        "default_provider": default,
        "safe_mode": llm_config.get("safe_mode", True),
        "provider_type": "disabled",
        "base_url": "",
        "api_key": "",
        "model": "",
        "timeout": llm_config.get("timeout_seconds", 30),
        "temperature": 0.2,
        "max_tokens": 1200,
    }

    if not result["enabled"] or default == "disabled":
        return result

    provider_cfg = providers.get(default, {})
    if not provider_cfg:
        return result

    result["provider_type"] = provider_cfg.get("type", "disabled")
    result["base_url"] = provider_cfg.get("base_url", "")
    result["model"] = provider_cfg.get("model", "")
    result["temperature"] = provider_cfg.get("temperature", 0.2)
    result["max_tokens"] = provider_cfg.get("max_tokens", 1200)

    # Resolve API key
    env = provider_cfg.get("api_key_env", "")
    file_path = provider_cfg.get("api_key_file", "")
    result["api_key"] = resolve_api_key(env_name=env, file_path=file_path) or ""

    return result


def get_llm_status() -> dict:
    """Get full LLM status for /api/agent/status."""
    cfg = load_llm_config()
    provider = resolve_provider_config(cfg)

    from agent.llm.schemas import ALLOWED_TASKS, BLOCKED_TASKS

    key_loaded = is_key_loaded()

    return {
        "enabled": cfg.get("enabled", False),
        "connected": key_loaded and provider["provider_type"] != "disabled",
        "provider": cfg.get("default_provider", "disabled"),
        "provider_type": provider["provider_type"],
        "model": provider["model"],
        "safe_mode": cfg.get("safe_mode", True),
        "allowed_tasks": sorted(ALLOWED_TASKS),
        "blocked_tasks": sorted(BLOCKED_TASKS),
        "config_source": "config/llm.yaml",
        "key_source": get_key_source(),
        "key_loaded": key_loaded,
        "health": _provider_health(provider),
        "red_lines": [
            "no_generate_deployable_config", "no_modify_deployable_config",
            "no_approve_manual_review", "no_bypass_translate_bundle",
            "no_bypass_skill_executor", "no_call_module_directly",
            "no_fake_planned_module_result",
        ],
    }


def _provider_health(provider: dict) -> dict:
    """Check provider health without leaking key."""
    try:
        from agent.llm.provider import health
        return health(provider)
    except Exception as e:
        return {"configured": bool(provider.get("api_key")),
                "connected": False, "last_error": _redact(str(e))}


def _default_config() -> dict:
    return {
        "enabled": False, "default_provider": "disabled", "safe_mode": True,
        "timeout_seconds": 30, "providers": {},
    }


def _load_yaml(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data.get("llm", data) if isinstance(data, dict) else {}
    except Exception:
        return {}


def _merge(base: dict, override: dict):
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v


def _apply_env_overrides(config: dict):
    if os.environ.get("NETWORK_AGENT_LLM_ENABLED"):
        val = os.environ["NETWORK_AGENT_LLM_ENABLED"].lower()
        if val in ("0", "false", "no"):
            config["enabled"] = False
        elif val in ("1", "true", "yes"):
            config["enabled"] = True
    if os.environ.get("LLM_PROVIDER"):
        config["default_provider"] = os.environ["LLM_PROVIDER"]


def _redact(msg: str) -> str:
    for kw in ["key", "password", "token", "auth"]:
        if kw.lower() in msg.lower():
            return f"[REDACTED] {msg[:40]}..."
    return msg[:100]


def mask_secret(value: str) -> str:
    return mask_secret(value)
