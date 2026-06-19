# agent/runtime/cognition/memory_policy.py
"""Memory policy — decides memory search/write actions for a turn."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class MemoryDecision:
    should_search: bool = False
    should_write: bool = False
    search_query: str = ""
    write_type: str = ""  # "profile", "fact", "preference"
    reason: str = ""


class MemoryPolicy:
    """Decide if memory search/write is needed based on scene signals."""

    def decide(self, user_input: str, signals: dict[str, Any] | None = None) -> MemoryDecision:
        signals = signals or {}
        mentions_memory = signals.get("mentions_memory", False)

        lower = (user_input or "").lower()
        wants_recall = any(k in lower for k in ("记忆", "记住", "remember", "recall", "profile", "偏好"))
        wants_write = any(k in lower for k in ("记住", "remember", "设置偏好", "profile.set"))

        return MemoryDecision(
            should_search=mentions_memory or wants_recall,
            should_write=wants_write,
            search_query=user_input if wants_recall else "",
            write_type="profile" if wants_write else "",
            reason="用户请求记忆操作" if mentions_memory else "",
        )
