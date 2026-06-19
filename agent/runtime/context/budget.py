# agent/runtime/context/budget.py
"""Context budget helpers — thin budget utilities for the context layer."""

from __future__ import annotations


def estimate_tokens(text: str) -> int:
    """Rough token estimate: len // 4 for ASCII, len // 2 for CJK."""
    if not text:
        return 0
    ascii_count = sum(1 for c in text if ord(c) < 128)
    cjk_count = len(text) - ascii_count
    return ascii_count // 4 + cjk_count // 2


def fits_budget(estimated: int, budget: int, threshold: float = 0.85) -> bool:
    """Check whether estimated tokens fit within threshold of budget."""
    return estimated <= int(budget * threshold)
