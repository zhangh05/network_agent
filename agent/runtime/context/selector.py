# agent/runtime/context/selector.py
"""Context selector — thin wrapper delegating to existing selector logic."""

from __future__ import annotations

from typing import Any


def select_for_frame(items: list[Any], budget_tokens: int = 8000) -> list[Any]:
    """Select context items within budget, delegating to existing selector.

    Thin wrapper that can call context.selector.select_context_items
    for the actual filtering logic.
    """
    try:
        from core.context.selector import select_context_items
        selected, _warnings = select_context_items(items)
        return selected
    except Exception:
        return items
