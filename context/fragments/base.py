# context/fragments/base.py
"""Composable context fragments — inspired by Codex's ContextualUserFragment trait.

Each fragment is a self-contained context source with:
- Independent ownership of its data fetch logic
- A hard token_budget cap (no fragment may exceed its budget)
- Priority ordering for injection
- Lazy evaluation via build()
- Serialization via render() for LLM prompt inclusion
"""

from __future__ import annotations

import enum
from typing import Any
from abc import ABC, abstractmethod


class FragmentPriority(enum.IntEnum):
    """Priority ordering for fragment injection. Lower = injected first."""
    ENVIRONMENT = 10       # workspace / session identity
    MEMORY = 20            # memory hits from past interactions
    REGISTRY = 30          # module/skill/tool availability
    BUSINESS_CONTEXT = 40  # domain-specific context (translation, knowledge)
    LLM_SAFE = 50          # safe_llm_context (last, closest to prompt)
    CUSTOM = 100           # user-defined fragments


class ContextFragment(ABC):
    """Base class for all context fragments.

    Each fragment MUST:
    - Declare a priority (FragmentPriority)
    - Set a token_budget (hard cap, bytes)
    - Implement build(state) -> dict (lazy, called once per run)
    - Implement render(data: dict) -> str (serialization for injection)

    Fragments are registered into FragmentRegistry and auto-collected
    during context loading.
    """

    priority: FragmentPriority = FragmentPriority.CUSTOM
    token_budget: int = 2048          # hard cap in approximate token bytes
    fragment_id: str = ""             # auto-set by registry

    def cap(self, text: str) -> str:
        """Truncate text to token_budget bytes."""
        encoded = text.encode("utf-8") if isinstance(text, str) else text
        if len(encoded) <= self.token_budget:
            return text
        truncated = encoded[: self.token_budget]
        # Try to cut at a UTF-8 boundary
        return truncated.decode("utf-8", errors="ignore") + "…"

    @abstractmethod
    def build(self, state: Any) -> dict:
        """Build this fragment's data from agent state.

        Called once per context load. Must return a dict with
        at least {'ok': bool}. Never raises — returns {'ok': False}
        on failure.
        """
        ...

    def render(self, data: dict) -> str:
        """Serialize built data for LLM prompt injection.

        Default implementation produces a key-value JSON-like summary.
        Override for domain-specific rendering.
        """
        if not data.get("ok"):
            return ""
        return self.cap(
            f"[{self.fragment_id}]\n"
            + "\n".join(f"  {k}: {v}" for k, v in data.items() if k != "ok")
        )
