# agent/runtime/prompting/budget.py
"""Prompt token budget helpers."""

from __future__ import annotations


def estimate_tokens(text: str) -> int:
    """Rough token estimation: ~4 chars per token for CJK+EN mixed text."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def estimate_prompt_tokens(fragments: list[str]) -> int:
    """Estimate total tokens for a list of prompt fragments."""
    return sum(estimate_tokens(f) for f in fragments)
