# agent/runtime/cognition/evidence_layers.py
"""EvidenceLayer — typed container for a single evidence source layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvidenceLayer:
    """A single layer of evidence from one source type."""

    layer_name: str = ""             # "context", "memory", "knowledge", "artifact"
    items: list[Any] = field(default_factory=list)
    trust_level: str = "untrusted"   # "highest", "high", "medium", "low", "untrusted", "excluded"
    policy: str = ""                 # policy name that governs this layer
    warnings: list[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.items)

    @property
    def is_empty(self) -> bool:
        return len(self.items) == 0
