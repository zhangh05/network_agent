# agent/runtime/memory/policy.py
"""Memory policies — read, write, and use policies for the memory layer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.runtime.memory.models import MemoryItem


@dataclass
class MemoryReadPolicy:
    """Policy governing which memories may be read and surfaced."""

    max_items: int = 10
    min_confidence: float = 0.3
    allowed_scopes: tuple[str, ...] = ("session", "workspace", "global")
    blocked_types: tuple[str, ...] = ()

    def allows(self, item: MemoryItem) -> bool:
        if item.confirmation_status == "rejected":
            return False
        if item.confidence < self.min_confidence:
            return False
        if item.scope not in self.allowed_scopes:
            return False
        if item.memory_type in self.blocked_types:
            return False
        return True


@dataclass
class MemoryWritePolicy:
    """Policy governing when memories may be written."""

    require_explicit_intent: bool = True
    allowed_types: tuple[str, ...] = ("profile", "fact", "preference")
    max_content_length: int = 2000

    def allows_write(self, user_input: str, memory_type: str, content: str) -> bool:
        if self.require_explicit_intent:
            lower = user_input.lower()
            explicit_markers = ("记住", "remember", "记忆", "设置偏好", "profile.set")
            if not any(m in lower for m in explicit_markers):
                return False
        if memory_type and memory_type not in self.allowed_types:
            return False
        if len(content) > self.max_content_length:
            return False
        return True


@dataclass
class MemoryUsePolicy:
    """Policy for how memory results are used in the prompt."""

    trust_confirmed: str = "medium"
    trust_unconfirmed: str = "low"
    trust_rejected: str = "excluded"

    def trust_level(self, item: MemoryItem) -> str:
        status = item.confirmation_status
        if status == "confirmed":
            return self.trust_confirmed
        if status == "rejected":
            return self.trust_rejected
        return self.trust_unconfirmed
