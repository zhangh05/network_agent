# agent/llm/config.py
"""LLM config loader — unified config with priority: UI settings > env > llm.local.yaml > llm.yaml."""

import os
import yaml
from pathlib import Path
from typing import Any, Dict, Optional

from agent.llm.key_resolver import resolve_api_key, get_key_source, is_key_loaded
from agent.llm.key_resolver import mask_secret as _key_mask  # use key_resolver's mask, not recursive

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
    """Get the active provider config with resolved API key.
    
    Priority: UI settings (config/LLM_setting.json) > env/file fallback > default.
    """
    # ═══ First: try UI settings (highest priority) ═══
    try:
        from agent.llm.settings import resolve_effective_llm_config as _resolve_ui
        ui_cfg = _resolve_ui()
        if ui_cfg.get("config_source") == "ui_settings":
            # UI settings exist — they are authoritative
            return ui_cfg
    except Exception:
        pass

    # ═══ Fallback: legacy env/file config (when no UI settings) ═══
    if llm_config is None:
        llm_config = load_llm_config()

    default = llm_config.get("default_provider", "disabled")
    providers = llm_config.get("providers", {})

    result = {
        "enabled": llm_config.get("enabled", False),
        "default_provider": default,
        "safe_mode": llm_config.get("safe_mode", True),
        "provider_type": "disabled",
        "provider": default,
        "base_url": "",
        "api_key": "",
        "model": "",
        "timeout": llm_config.get("timeout_seconds", 30),
        "temperature": 0.2,
        "max_tokens": 4096,
        "config_source": "file",
        "key_loaded": False,
        "key_source": "none",
        "enabled_by_ui": None,  # no UI settings
    }

    if not result["enabled"] or default == "disabled":
        return result

    provider_cfg = providers.get(default, {})
    if not provider_cfg:
        return result

    result["provider_type"] = provider_cfg.get("type", "disabled")
    result["base_url"] = provider_cfg.get("base_url", "")
    result["model"] = provider_cfg.get("model", "")

    # LEGACY MIGRATION: Migrate MiniMax-M1 → M3 (user may have old config).
    # MiniMax-M1 is a prohibited default. Current default is MiniMax-M3.
    if result["model"] == "MiniMax-M1":
        result["model"] = "MiniMax-M3"

    result["temperature"] = provider_cfg.get("temperature", 0.2)
    result["max_tokens"] = provider_cfg.get("max_tokens", 4096)

    # Resolve API key from env/file
    env = provider_cfg.get("api_key_env", "")
    file_path = provider_cfg.get("api_key_file", "")
    result["api_key"] = resolve_api_key(env_name=env, file_path=file_path) or ""
    result["key_loaded"] = bool(result["api_key"]) or is_key_loaded()
    result["key_source"] = get_key_source() or "none"

    # Env override takes precedence over file
    if os.environ.get("MINIMAX_API_KEY") or os.environ.get("OPENAI_API_KEY"):
        result["config_source"] = "env"
        result["key_loaded"] = True

    return result


def get_llm_status() -> dict:
    """Get full LLM status for /api/agent/llm/status."""
    cfg = load_llm_config()
    provider = resolve_provider_config(cfg)

    from agent.llm.schemas import ALLOWED_TASKS, BLOCKED_TASKS

    key_loaded = provider.get("key_loaded", False) or is_key_loaded()
    health = _provider_health(provider)
    connected = _is_connected(provider, key_loaded, health)

    return {
        "enabled": provider.get("enabled", False),
        "connected": connected,
        "provider": provider.get("provider", provider.get("default_provider", "disabled")),
        "provider_type": provider.get("provider_type", "disabled"),
        "model": provider.get("model", ""),
        "safe_mode": provider.get("safe_mode", True),
        "allowed_tasks": sorted(ALLOWED_TASKS),
        "blocked_tasks": sorted(BLOCKED_TASKS),
        "config_source": provider.get("config_source", "default"),
        "key_source": provider.get("key_source", get_key_source()),
        "key_loaded": key_loaded,
        "enabled_by_ui": provider.get("enabled_by_ui"),
        "settings_file_exists": provider.get("config_source") == "ui_settings",
        "health": health,
        "recent_failure": _read_recent_failure(),
        "last_success": _read_recent_success(),
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


def _is_connected(provider: dict, key_loaded: bool, health: dict) -> bool:
    """Return the user-facing connection state.

    A configured key alone is not enough: users can only treat the LLM as
    connected when the chat completions path is actually usable.
    """
    if not provider.get("enabled", False):
        return False
    if provider.get("provider_type", "disabled") == "disabled":
        return False
    if not key_loaded:
        return False
    return bool(health.get("chat_completion_ok"))


# ── Recent failure tracking for LLM health UX ──

_FAILURE_FILE = "workspaces/_runtime/llm_recent_failure.json"


def record_recent_failure(error_summary: str, error_type: str = "") -> None:
    """Called by the runtime when an LLM turn fails, so the health
    bar can show a diagnostic even when normal probing passes."""
    import json, os, time
    from pathlib import Path
    from workspace.run_store import WS_ROOT
    path = WS_ROOT / "_runtime" / "llm_recent_failure.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "error_summary": error_summary[:200],
        "error_type": error_type[:100],
    }
    _atomic_write_json_cfg(path, record)


def record_recent_success() -> None:
    """Called by the runtime when an LLM turn succeeds, so Settings
    can show success state alongside any stale failure record."""
    import time
    from pathlib import Path
    from workspace.run_store import WS_ROOT
    path = WS_ROOT / "_runtime" / "llm_recent_success.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_json_cfg(path, {"at": time.strftime("%Y-%m-%dT%H:%M:%S")})

def _read_recent_success() -> dict | None:
    """Return the most recent LLM success record, or None."""
    import json
    from pathlib import Path
    from workspace.run_store import WS_ROOT
    path = WS_ROOT / "_runtime" / "llm_recent_success.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _read_recent_failure() -> dict | None:
    """Return the most recent LLM failure record, or None."""
    import json
    from pathlib import Path
    from workspace.run_store import WS_ROOT
    path = WS_ROOT / "_runtime" / "llm_recent_failure.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _atomic_write_json_cfg(path, data: dict) -> None:
    import json
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.rename(path)


def _default_config() -> dict:
    return {
        "enabled": False, "default_provider": "disabled", "safe_mode": True,
        "timeout_seconds": 90, "providers": {},
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
            return "[REDACTED] sensitive error"
    return msg[:100]


# Re-export mask_secret from key_resolver (fixes recursion bug)
def mask_secret(value: str, show_chars: int = 4) -> str:
    """Mask a secret string for safe display. Delegates to key_resolver."""
    return _key_mask(value, show_chars)
