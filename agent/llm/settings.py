# agent/llm/settings.py
"""LLM Settings — CRUD for config/LLM_setting.json, priority over env/file fallback."""

import json, os, stat
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent.parent
SETTINGS_PATH = ROOT / "config" / "LLM_setting.json"


def get_llm_setting_path() -> str:
    return str(SETTINGS_PATH)


def load_llm_settings() -> Optional[dict]:
    if not SETTINGS_PATH.is_file():
        return None
    try:
        data = json.loads(SETTINGS_PATH.read_text())
        # Migrate MiniMax-M1 to MiniMax-M3
        if data.get("model") == "MiniMax-M1":
            data["model"] = "MiniMax-M3"
        return data
    except Exception:
        return None


def save_llm_settings(data: dict) -> dict:
    existing = load_llm_settings() or {}
    data = dict(data)

    if data.get("provider") == "openai_compatible":
        data["provider_type"] = "openai_compatible"
    elif data.get("provider") == "ollama_compatible":
        data["provider_type"] = "ollama_compatible"

    # Preserve existing key if not provided
    if "api_key" not in data or not data.get("api_key"):
        if data.get("clear_api_key"):
            data["api_key"] = ""
        elif existing.get("api_key"):
            data["api_key"] = existing["api_key"]

    # Set defaults for minimax
    if data.get("provider") == "minimax":
        if not data.get("model"):
            data["model"] = "MiniMax-M3"
        if not data.get("base_url"):
            data["base_url"] = "https://api.minimax.chat/v1"
    # Migrate any M1 references
    if data.get("model") == "MiniMax-M1":
        data["model"] = "MiniMax-M3"

    from datetime import datetime, timezone
    data["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    SETTINGS_PATH.parent.mkdir(exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    # Set owner-only permissions if possible
    try:
        os.chmod(str(SETTINGS_PATH), stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        pass

    return data


def delete_llm_settings() -> bool:
    if SETTINGS_PATH.is_file():
        SETTINGS_PATH.unlink()
        return True
    return False


def sanitize_llm_settings(data: dict) -> dict:
    if not data:
        return {"enabled": False, "provider": "disabled"}
    key = data.get("api_key", "")
    result = {
        "enabled": data.get("enabled", False),
        "provider": data.get("provider", "disabled"),
        "safe_mode": data.get("safe_mode", True),
        "base_url": data.get("base_url", ""),
        "model": data.get("model", ""),
        "temperature": data.get("temperature", 0.2),
        "max_tokens": data.get("max_tokens", 4096),
        "key_configured": bool(key),
        "key_preview": mask_key(key) if key else None,
        "updated_at": data.get("updated_at"),
    }
    return result


def mask_key(key: str) -> str:
    if not key or len(key) < 8:
        return None
    return key[:4] + "****" + key[-4:]


def resolve_effective_llm_config() -> dict:
    """Return effective config with priority: UI settings > env/file fallback > default."""
    ui = load_llm_settings()

    if ui is not None:
        # UI settings exist — respect them
        provider = ui.get("provider", "disabled")
        provider_type = ui.get("provider_type")
        if not provider_type:
            if provider == "minimax":
                provider_type = "openai_compatible"
            elif provider in ("openai_compatible", "ollama_compatible", "mock", "disabled"):
                provider_type = provider
            else:
                provider_type = provider or "disabled"
        result = {
            "enabled": ui.get("enabled", False),
            "provider": provider,
            "safe_mode": ui.get("safe_mode", True),
            "base_url": ui.get("base_url", ""),
            "model": ui.get("model", ""),
            "temperature": ui.get("temperature", 0.2),
            "max_tokens": ui.get("max_tokens", 1200),
            "api_key": ui.get("api_key", ""),
            "provider_type": provider_type,
            "config_source": "ui_settings",
            "key_loaded": bool(ui.get("api_key")),
            "key_source": "ui_settings",
            "default_provider": provider,
            "timeout": 30,
        }
        # If UI says disabled, enforce it regardless of env
        if not result["enabled"]:
            return result
        return result

    # No UI settings — fallback to env/file
    from agent.llm.key_resolver import resolve_api_key, get_key_source, is_key_loaded
    from agent.llm.config import load_llm_config

    cfg = load_llm_config()
    env_key = resolve_api_key(env_name="MINIMAX_API_KEY")
    default = cfg.get("default_provider", "disabled")
    providers = cfg.get("providers", {})
    provider_cfg = providers.get(default, {})

    # Migrate M1→M3 in provider config
    model = provider_cfg.get("model", "")
    if model == "MiniMax-M1":
        model = "MiniMax-M3"

    result = {
        "enabled": cfg.get("enabled", False) or bool(env_key),
        "provider": default,
        "safe_mode": cfg.get("safe_mode", True),
        "base_url": provider_cfg.get("base_url", ""),
        "model": model,
        "temperature": provider_cfg.get("temperature", 0.2),
        "max_tokens": provider_cfg.get("max_tokens", 1200),
        "api_key": env_key or "",
        "provider_type": provider_cfg.get("type", "disabled"),
        "config_source": "env" if env_key else "file" if is_key_loaded() else "default",
        "key_loaded": bool(env_key) or is_key_loaded(),
        "key_source": get_key_source() or "none",
        "default_provider": default,
        "timeout": cfg.get("timeout_seconds", 30),
    }
    return result


def validate_llm_settings(data: dict) -> list:
    errors = []
    valid_providers = [
        "minimax", "disabled", "mock", "openai",
        "deepseek", "ollama", "custom",
        "openai_compatible", "ollama_compatible",
    ]
    if data.get("provider") not in valid_providers:
        errors.append(f"invalid provider: {data.get('provider')}")
    bu = data.get("base_url", "")
    if bu and not (bu.startswith("http://") or bu.startswith("https://")):
        errors.append("base_url must start with http:// or https://")
    if not data.get("model") and data.get("provider") not in ("disabled", "mock"):
        # minimax auto-fills MiniMax-M3 in save_llm_settings; allow empty
        if data.get("provider") not in ("minimax", "ollama_compatible"):
            errors.append("model is required")
    temp = data.get("temperature", 0.7)
    if not isinstance(temp, (int, float)) or temp < 0 or temp > 2:
        errors.append("temperature must be 0-2")
    mt = data.get("max_tokens", 4096)
    if not isinstance(mt, int) or mt < 1 or mt > 128000:
        errors.append("max_tokens must be 1-128000")
    return errors
