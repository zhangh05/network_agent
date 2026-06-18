# agent/llm/settings.py
"""LLM Settings — CRUD for config/LLM_setting.json, priority over env/file fallback.

Config precedence (lowest to highest):
1. default (disabled, no key)
2. file (config/llm.yaml, config/llm.local.yaml)
3. env (MINIMAX_API_KEY, LLM_PROVIDER, etc.)
4. auto_default (auto-generated config/LLM_setting.json with source="auto_default")
5. ui_settings (user-saved config/LLM_setting.json with source="ui_settings")

Rules:
- auto_default with enabled=false MUST NOT override env key (if MINIMAX_API_KEY exists → enabled=true)
- ui_settings with enabled=false → respected (user explicitly disabled)
- ui_settings with api_key → use UI key (highest priority)
"""

import json, os, stat
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent.parent
SETTINGS_PATH = ROOT / "config" / "LLM_setting.json"

# Source constants (used in config_source field)
SOURCE_AUTO_DEFAULT = "auto_default"
SOURCE_UI_SETTINGS = "ui_settings"
SOURCE_ENV = "env"
SOURCE_FILE = "file"
SOURCE_DEFAULT = "default"


def get_llm_setting_path() -> str:
    return str(SETTINGS_PATH)


def _ensure_default_exists():
    """Create config/LLM_setting.json from example template on first access.
    
    Marks it as source="auto_default" so the resolver knows
    it should not override env keys.
    """
    example = SETTINGS_PATH.parent / "LLM_setting.example.json"
    if example.is_file() and not SETTINGS_PATH.is_file():
        try:
            from datetime import datetime, timezone
            data = json.loads(example.read_text())
            # Mark as auto-generated default
            data["source"] = SOURCE_AUTO_DEFAULT
            data["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            SETTINGS_PATH.parent.mkdir(exist_ok=True)
            SETTINGS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False))
            try:
                os.chmod(str(SETTINGS_PATH), stat.S_IRUSR | stat.S_IWUSR)
            except Exception:
                pass
        except Exception:
            pass


def load_llm_settings() -> Optional[dict]:
    if not SETTINGS_PATH.is_file():
        _ensure_default_exists()
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
    """Save LLM settings — always marks as ui_settings."""
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
            data["base_url"] = "https://api.minimaxi.com/v1"
    # Migrate any M1 references
    if data.get("model") == "MiniMax-M1":
        data["model"] = "MiniMax-M3"

    from datetime import datetime, timezone
    data["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # Mark as user_saved (highest priority, explicit action)
    data["source"] = SOURCE_UI_SETTINGS

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
        "max_tokens": data.get("max_tokens", 1200),
        "key_configured": bool(key),
        "key_preview": mask_key(key) if key else None,
        "updated_at": data.get("updated_at"),
        "source": data.get("source", SOURCE_AUTO_DEFAULT),
    }
    return result


def mask_key(key: str) -> str:
    if not key or len(key) < 8:
        return None
    return key[:4] + "****" + key[-4:]


def resolve_effective_llm_config() -> dict:
    """Return effective config with priority: provider_store (active provider) > env > file > default.
    
    Uses the new per-provider config system (config/providers/).
    Falls back to previous LLM_setting.json when provider files are absent.
    """
    from agent.llm.key_resolver import resolve_api_key, get_key_source, is_key_loaded
    from agent.llm.config import load_llm_config

    # An explicit legacy settings file with enabled=false is a deliberate
    # user/test disable and must not be bypassed by an active provider file.
    ui = load_llm_settings()
    if ui is not None and ui.get("enabled") is False:
        return _build_ui_config(ui, ui.get("source", SOURCE_UI_SETTINGS))

    # ═══ 1. Try per-provider active config (new system) ═══
    try:
        from agent.llm.provider_store import get_active_config, get_active_provider
        active_cfg = get_active_config()
        if active_cfg and active_cfg.get("enabled"):
            active_id = get_active_provider()
            api_key = active_cfg.get("api_key", "")
            if not api_key:
                env_key = resolve_api_key(env_name="MINIMAX_API_KEY")
                if env_key:
                    api_key = env_key
            return {
                "enabled": active_cfg.get("enabled", True),
                "provider": active_id,
                "safe_mode": active_cfg.get("safe_mode", True),
                "base_url": active_cfg.get("base_url", ""),
                "model": active_cfg.get("model", ""),
                "temperature": active_cfg.get("temperature", 0.2),
                "max_tokens": active_cfg.get("max_tokens", 1200),
                "api_key": api_key,
                "provider_type": "openai_compatible",
                "config_source": SOURCE_UI_SETTINGS,
                "key_loaded": bool(api_key) or is_key_loaded(),
                "key_source": "ui_settings" if active_cfg.get("api_key") else (get_key_source() or "none"),
                "default_provider": active_id,
                "timeout": 90,
                "source": SOURCE_UI_SETTINGS,
                "enabled_by_ui": True,
                "key_fallback_used": not bool(active_cfg.get("api_key")) and bool(api_key),
            }
    except Exception:
        pass

    # ═══ 2. Previous LLM_setting.json fallback ═══
    if ui is not None:
        source = ui.get("source", SOURCE_UI_SETTINGS)
        
        # ui_settings: highest priority, always respected
        if source == SOURCE_UI_SETTINGS:
            return _build_ui_config(ui, source)
        
        # auto_default: MUST NOT override env key
        if source == SOURCE_AUTO_DEFAULT:
            env_key = resolve_api_key(env_name="MINIMAX_API_KEY")
            cfg = _build_ui_config(ui, source)
            if env_key and not cfg.get("enabled"):
                cfg["enabled"] = True
                cfg["enabled_reason"] = "env_key_override_auto_default"
                cfg["config_source"] = SOURCE_ENV
            return cfg
        
        return _build_ui_config(ui, source)

    # 2. No UI settings — fallback to env/file
    cfg = load_llm_config()
    env_key = resolve_api_key(env_name="MINIMAX_API_KEY")
    
    result = {
        "enabled": cfg.get("enabled", False) or bool(env_key),
        "provider": cfg.get("default_provider", "disabled"),
        "safe_mode": cfg.get("safe_mode", True),
        "base_url": "",
        "model": "",
        "temperature": 0.2,
        "max_tokens": 4096,
        "api_key": env_key or "",
        "provider_type": "disabled",
        "config_source": SOURCE_ENV if env_key else SOURCE_FILE,
        "key_loaded": bool(env_key) or is_key_loaded(),
        "key_source": get_key_source() or "none",
        "default_provider": cfg.get("default_provider", "disabled"),
        "timeout": cfg.get("timeout_seconds", 90),
    }

    # Merge provider-specific config
    providers = cfg.get("providers", {})
    default_provider = cfg.get("default_provider", "disabled")
    provider_cfg = providers.get(default_provider, {})
    if provider_cfg:
        result["provider_type"] = provider_cfg.get("type", "disabled")
        result["base_url"] = provider_cfg.get("base_url", "")
        result["model"] = provider_cfg.get("model", "")
        result["temperature"] = provider_cfg.get("temperature", 0.2)
        result["max_tokens"] = provider_cfg.get("max_tokens", 4096)
        # Only use file key if env key not present
        if not env_key:
            file_key = resolve_api_key(
                env_name=provider_cfg.get("api_key_env", ""),
                file_path=provider_cfg.get("api_key_file", ""),
            )
            result["api_key"] = file_key or ""

    # Env override takes precedence
    if os.environ.get("MINIMAX_API_KEY") or os.environ.get("OPENAI_API_KEY"):
        result["config_source"] = SOURCE_ENV
        result["key_loaded"] = True

    return result


def _build_ui_config(ui: dict, source: str) -> dict:
    """Build config dict from UI settings."""
    from agent.llm.key_resolver import resolve_api_key, get_key_source, is_key_loaded
    
    provider = ui.get("provider", "disabled")
    provider_type = ui.get("provider_type")
    if not provider_type:
        if provider == "minimax":
            provider_type = "openai_compatible"
        elif provider in ("openai_compatible", "ollama_compatible", "mock", "disabled"):
            provider_type = provider
        else:
            provider_type = provider or "disabled"
    
    api_key = ui.get("api_key", "")
    enabled = ui.get("enabled", False)
    key_fallback_used = False
    key_source = "none"

    if source == SOURCE_UI_SETTINGS:
        if api_key:
            # Rule 1: UI settings file has api_key
            key_source = "ui_settings"
        elif enabled and not api_key:
            # Rule 2: UI settings enabled=true, no api_key in file
            env_key = resolve_api_key(env_name="MINIMAX_API_KEY")
            if env_key:
                api_key = env_key
                key_source = "env_fallback"
                key_fallback_used = True
            else:
                key_source = get_key_source() or "none"
        elif not enabled:
            # Rule 3: UI settings enabled=false — deliberate disable
            # Do NOT fall back to env key
            key_source = "none"
            api_key = ""
    elif source == SOURCE_AUTO_DEFAULT:
        # auto_default: use env key as fallback
        if not api_key:
            env_key = resolve_api_key(env_name="MINIMAX_API_KEY")
            if env_key:
                api_key = env_key
                key_source = "env"
            else:
                key_source = get_key_source() or "none"
        else:
            key_source = "ui_settings"
    else:
        # Unknown source: use env key as fallback
        if not api_key:
            env_key = resolve_api_key(env_name="MINIMAX_API_KEY")
            if env_key:
                api_key = env_key
        key_source = "ui_settings" if api_key else (get_key_source() or "none")

    result = {
        "enabled": enabled,
        "provider": provider,
        "safe_mode": ui.get("safe_mode", True),
        "base_url": ui.get("base_url", ""),
        "model": ui.get("model", ""),
        "temperature": ui.get("temperature", 0.2),
        "max_tokens": ui.get("max_tokens", 1200),
        "api_key": api_key,
        "provider_type": provider_type,
        "config_source": source,
        "key_loaded": bool(api_key) or (enabled and is_key_loaded()),
        "key_source": key_source,
        "key_fallback_used": key_fallback_used,
        "default_provider": provider,
        "timeout": 90,
        "source": source,
    }
    return result


def validate_llm_settings(data: dict) -> list:
    errors = []
    valid_providers = [
        "minimax", "disabled", "mock", "openai",
        "deepseek", "ollama", "custom",
        "openai_compatible", "ollama_compatible",
        "ark", "anthropic",
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
