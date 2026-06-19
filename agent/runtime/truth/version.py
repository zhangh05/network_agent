# agent/runtime/truth/version.py
"""VersionTruth — single source of truth for runtime version."""

from __future__ import annotations

_VERSION = "3.2.0"
_CODENAME = "core-finalization"


class VersionTruth:
    """Provide the authoritative runtime version."""

    @staticmethod
    def version() -> str:
        return _VERSION

    @staticmethod
    def codename() -> str:
        return _CODENAME

    @staticmethod
    def full() -> str:
        return f"{_VERSION} ({_CODENAME})"
