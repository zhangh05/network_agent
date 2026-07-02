"""
SSOT Runtime v10.1 Context Seal — canonical serialization + SHA-256.

Canonical serializer ensures structural stability: same content
always produces the same hash regardless of dict ordering.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_serialize(snapshot: list[dict]) -> str:
    """v10.1: deterministic serialization — sort_keys + minimal separators."""
    return json.dumps(list(snapshot), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, default=str)


class ContextSeal:
    """v10.1: seal a context snapshot with canonical hash."""

    @staticmethod
    def seal(snapshot: list[dict]) -> dict[str, Any]:
        serialized = canonical_serialize(snapshot)
        h = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        return {
            "hash": h,
            "snapshot": snapshot,
            "sealed": True,
        }

    @staticmethod
    def verify(sealed: dict[str, Any]) -> bool:
        if not sealed.get("sealed"):
            return False
        snapshot = sealed.get("snapshot")
        if snapshot is None:
            return False
        expected = hashlib.sha256(
            canonical_serialize(snapshot).encode("utf-8")
        ).hexdigest()
        return expected == sealed["hash"]

    @staticmethod
    def unseal(sealed: dict[str, Any]) -> list[dict] | None:
        if ContextSeal.verify(sealed):
            return list(sealed["snapshot"])
        return None


__all__ = ["ContextSeal", "canonical_serialize"]

