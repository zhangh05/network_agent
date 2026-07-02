"""
SPEG v10 Context Seal — immutable, verifiable context snapshot.

Once sealed, context cannot be modified.  The seal hash allows
downstream verification that the context was not tampered with.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


class ContextSeal:
    """v10: seal a context snapshot for immutability + verification."""

    @staticmethod
    def seal(snapshot: list[dict]) -> dict[str, Any]:
        """Seal a list of context events into a verifiable snapshot."""
        serialized = json.dumps(snapshot, sort_keys=True, ensure_ascii=False,
                                default=str)
        h = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        return {
            "hash": h,
            "snapshot": snapshot,
            "sealed": True,
        }

    @staticmethod
    def verify(sealed: dict[str, Any]) -> bool:
        """Verify that the snapshot matches the seal hash."""
        if not sealed.get("sealed"):
            return False
        snapshot = sealed.get("snapshot")
        if snapshot is None:
            return False
        serialized = json.dumps(list(snapshot), sort_keys=True,
                                ensure_ascii=False, default=str)
        expected = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        return expected == sealed["hash"]

    @staticmethod
    def unseal(sealed: dict[str, Any]) -> list[dict] | None:
        """Return the snapshot if the seal is valid, None otherwise."""
        if ContextSeal.verify(sealed):
            return list(sealed["snapshot"])
        return None


__all__ = ["ContextSeal"]
