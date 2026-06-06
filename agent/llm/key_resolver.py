# agent/llm/key_resolver.py
"""Secure API key resolution — env vars and local files only. Never in code."""

import os
import re
from pathlib import Path
from typing import Optional

KEY_SOURCES = []


def resolve_api_key(env_name: str = "", file_path: str = "") -> Optional[str]:
    """Resolve API key from env or local file. Never logs or stores plaintext."""
    global KEY_SOURCES
    KEY_SOURCES.clear()  # Reset on each call to avoid stale state

    # 1. Environment variable
    if env_name and os.environ.get(env_name):
        KEY_SOURCES.append(f"env:{env_name}")
        return os.environ[env_name]

    # If explicit env_name given but not found, don't fall back to auto-detect
    explicit_request = bool(env_name) or bool(file_path)

    # 2. Explicit file path
    if file_path:
        path = Path(file_path).expanduser()
        if path.is_file():
            key = _read_key_from_file(str(path))
            if key:
                KEY_SOURCES.append(f"file:{path}")
                return key

    # Only auto-detect when no explicit env/file specified
    if explicit_request:
        return None

    # 3. Auto-detect desktop api key files
    for name in ["apikey", "api_key", "minimax_apikey", "minimax_api_key", "API_key.txt"]:
        for base in [Path.home() / "Desktop", Path.home()]:
            p = base / name
            if p.is_file():
                key = _read_key_from_file(str(p))
                if key:
                    KEY_SOURCES.append(f"auto:{p.name}")
                    return key

    return None


def _read_key_from_file(path: str) -> Optional[str]:
    """Read key from file, supporting multiple formats."""
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read().strip()
    except Exception:
        return None

    # Multi-line: look for KEY=VALUE or KEY: VALUE
    for line in content.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # KEY=VALUE
        if "=" in line:
            _, val = line.split("=", 1)
            val = val.strip()
            if val and not val.startswith("#"):
                return val
        # KEY: VALUE
        if ":" in line and not line.startswith("http"):
            _, val = line.split(":", 1)
            val = val.strip()
            if val and not val.startswith("#") and len(val) > 8:
                return val

    # Single-line: raw key
    if len(content) > 8 and not content.startswith("http"):
        return content

    return None


def get_key_source() -> str:
    """Return where the key was loaded from (no key value)."""
    if KEY_SOURCES:
        return KEY_SOURCES[-1]
    return "none"


def is_key_loaded() -> bool:
    """Check if key was loaded."""
    return len(KEY_SOURCES) > 0


def mask_secret(value: str, show_chars: int = 4) -> str:
    """Mask a secret string for safe display."""
    if not value:
        return ""
    if len(value) <= show_chars * 2:
        return "*" * len(value)
    return value[:show_chars] + "****" + value[-show_chars:]
