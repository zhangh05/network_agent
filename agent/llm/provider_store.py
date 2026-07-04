# agent/llm/provider_store.py
"""Per-provider config file management.

Each LLM provider stores its configuration independently:
  config/providers/<provider_id>.json

Active provider selection is tracked in:
  config/providers/_active  (plain text, one line: the active provider id)

"""

import json
import os
import stat
from pathlib import Path
from typing import Optional

from agent.runtime.utils import now_iso
ROOT = Path(__file__).resolve().parent.parent.parent
PROVIDERS_DIR = ROOT / "config" / "providers"
ACTIVE_FILE = PROVIDERS_DIR / "_active"

# ── Built-in provider presets ──

PROVIDER_PRESETS: dict = {
    "minimax": {
        "id": "minimax",
        "label": "MiniMax",
        "base_url": "https://api.minimaxi.com/v1",
        "model": "MiniMax-M3",
        "hint": "api.minimaxi.com",
    },
    "deepseek": {
        "id": "deepseek",
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "hint": "api.deepseek.com",
    },
    "ark": {
        "id": "ark",
        "label": "方舟 (豆包)",
        "base_url": "https://ark.cn-beijing.volces.com/api/coding/v3",
        "model": "ark-code-latest",
        "hint": "ark.volces.com",
    },
    "openai": {
        "id": "openai",
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "hint": "api.openai.com",
    },
    "anthropic": {
        "id": "anthropic",
        "label": "Anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "model": "claude-3-haiku-20240307",
        "hint": "api.anthropic.com",
    },
    "ollama": {
        "id": "ollama",
        "label": "Ollama (本地)",
        "base_url": "http://localhost:11434/v1",
        "model": "llama3.1",
        "hint": "localhost:11434",
    },
    "custom": {
        "id": "custom",
        "label": "自定义",
        "base_url": "",
        "model": "",
        "hint": "OpenAI 兼容 API",
    },
}


def _ensure_dir():
    PROVIDERS_DIR.mkdir(parents=True, exist_ok=True)


def _provider_path(provider_id: str) -> Path:
    return PROVIDERS_DIR / f"{provider_id}.json"


def _build_provider_config(provider_id: str, data: Optional[dict] = None) -> dict:
    """Build a clean provider config dict, merging preset defaults with stored data."""
    preset = PROVIDER_PRESETS.get(provider_id, PROVIDER_PRESETS["custom"])
    cfg = {
        "provider": provider_id,
        "label": preset["label"],
        "enabled": True,
        "base_url": preset["base_url"],
        "model": preset["model"],
        "temperature": 0.2,
        "max_tokens": 1200,
        "safe_mode": True,
        "api_key": "",
        "hint": preset.get("hint", ""),
        "updated_at": None,
    }
    if data:
        for key in ("enabled", "base_url", "model", "temperature", "max_tokens",
                     "safe_mode", "api_key", "label"):
            if key in data:
                cfg[key] = data[key]
        if data.get("updated_at"):
            cfg["updated_at"] = data["updated_at"]
    return cfg


def _write_json(path: Path, data: dict):
    _ensure_dir()
    data["updated_at"] = now_iso()
    # Atomic write: tmp + rename to prevent corruption on crash.
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    try:
        os.chmod(str(tmp), stat.S_IRUSR | stat.S_IWUSR)
    except Exception:
        pass
    tmp.replace(path)


def _write_active(provider_id: str):
    _ensure_dir()
    ACTIVE_FILE.write_text(provider_id)


def _sanitize(data: dict) -> dict:
    """Return a sanitized version for API responses (mask API key)."""
    key = data.get("api_key", "")
    return {
        **data,
        "key_configured": bool(key),
        "key_preview": _mask_key(key) if key else None,
        "api_key": None,  # never return the key
    }


def _mask_key(key: str) -> Optional[str]:
    if not key or len(key) < 8:
        return None
    return key[:4] + "****" + key[-4:]


# ── Public API ──


def list_providers() -> list[dict]:
    """Return all provider configs (sanitized), with active flag."""
    _ensure_dir()

    active = get_active_provider()
    result = []

    for provider_id in PROVIDER_PRESETS:
        cfg = load_provider_config(provider_id)
        sanitized = _sanitize(cfg)
        sanitized["is_active"] = (provider_id == active)
        result.append(sanitized)

    return result


def load_provider_config(provider_id: str) -> dict:
    """Load one provider's config. Falls back to preset defaults if no file exists."""
    _ensure_dir()
    path = _provider_path(provider_id)

    if path.is_file():
        try:
            stored = json.loads(path.read_text())
            return _build_provider_config(provider_id, stored)
        except Exception:
            pass

    return _build_provider_config(provider_id, None)


def save_provider_config(provider_id: str, data: dict) -> dict:
    """Save one provider's config. Merges incoming fields with existing."""
    existing = load_provider_config(provider_id)

    # Merge allowed fields from incoming data
    for key in ("enabled", "base_url", "model", "temperature", "max_tokens",
                 "safe_mode", "label"):
        if key in data:
            existing[key] = data[key]

    # API key handling
    if "api_key" in data and data["api_key"]:
        existing["api_key"] = data["api_key"]
    elif data.get("clear_api_key"):
        existing["api_key"] = ""

    _write_json(_provider_path(provider_id), existing)
    return existing


def get_active_provider() -> str:
    """Return the currently active provider id. Defaults to 'custom'."""
    _ensure_dir()
    if ACTIVE_FILE.is_file():
        try:
            pid = ACTIVE_FILE.read_text().strip()
            if pid in PROVIDER_PRESETS:
                return pid
        except Exception:
            pass
    return "custom"


def set_active_provider(provider_id: str) -> bool:
    """Activate a provider. Saves its current config first, then marks it active."""
    if provider_id not in PROVIDER_PRESETS:
        return False
    _write_active(provider_id)
    return True


def get_active_config() -> dict:
    """Get the full (unsanitized) config of the active provider for LLM runtime."""
    active = get_active_provider()
    return load_provider_config(active)


def delete_provider_config(provider_id: str) -> bool:
    """Delete a provider's config file (reset to preset defaults)."""
    path = _provider_path(provider_id)
    if path.is_file():
        path.unlink()
        return True
    return False
