# agent/runtime/truth/version.py
"""VersionTruth — single source of truth for runtime version.

Resolution order:
1. agent.__version__ (if exists)
2. pyproject.toml [project] version (if exists)
3. Fallback to hardcoded _FALLBACK_VERSION (with warning)
"""

from __future__ import annotations

import os

_FALLBACK_VERSION = "3.2.0"
_CODENAME = "core-finalization"


def _resolve_version() -> tuple[str, bool]:
    """Return (version, is_fallback)."""
    # 1. Try agent.__version__
    try:
        import agent  # noqa: F401

        ver = getattr(agent, "__version__", None)
        if ver:
            return str(ver), False
    except Exception:
        pass

    # 2. Try pyproject.toml
    try:
        project_root = os.path.join(os.path.dirname(__file__), "..", "..", "..")
        toml_path = os.path.join(project_root, "pyproject.toml")
        if os.path.isfile(toml_path):
            with open(toml_path, "r", encoding="utf-8") as fh:
                for line in fh:
                    stripped = line.strip()
                    if stripped.startswith("version") and "=" in stripped:
                        val = stripped.split("=", 1)[1].strip().strip("\"'")
                        if val:
                            return val, False
    except Exception:
        pass

    # 3. Fallback
    return _FALLBACK_VERSION, True


_RESOLVED_VERSION, _IS_FALLBACK = _resolve_version()


class VersionTruth:
    """Provide the authoritative runtime version."""

    @staticmethod
    def version() -> str:
        return _RESOLVED_VERSION

    @staticmethod
    def codename() -> str:
        return _CODENAME

    @staticmethod
    def full() -> str:
        return f"{_RESOLVED_VERSION} ({_CODENAME})"

    @staticmethod
    def is_fallback() -> bool:
        return _IS_FALLBACK

    @staticmethod
    def warnings() -> list[str]:
        if _IS_FALLBACK:
            return ["version_fallback_used: no pyproject.toml or agent.__version__ found"]
        return []
