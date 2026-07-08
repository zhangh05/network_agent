# agent/runtime/prompting/budget.py
"""Prompt token budget helpers."""

from __future__ import annotations


def estimate_tokens(text: str) -> int:
    """Rough token estimation (CJK-aware).

    CJK characters: ~1 char per token.
    Latin/ASCII: ~4 chars per token.
    """
    if not text:
        return 0
    s = str(text)
    cjk = sum(1 for c in s if _is_cjk(c))
    non_cjk = len(s) - cjk
    return max(1, cjk + non_cjk // 4)


def _is_cjk(c: str) -> bool:
    cp = ord(c)
    return (
        0x4E00 <= cp <= 0x9FFF or    # CJK Unified Ideographs
        0x3400 <= cp <= 0x4DBF or    # CJK Extension A
        0x3000 <= cp <= 0x303F or    # CJK Symbols and Punctuation
        0x31C0 <= cp <= 0x31EF or    # CJK Strokes
        0x3200 <= cp <= 0x32FF or    # Enclosed CJK Letters
        0x3300 <= cp <= 0x33FF or    # CJK Compatibility
        0xFE30 <= cp <= 0xFE4F or    # CJK Compatibility Forms
        0xFF00 <= cp <= 0xFFEF       # Halfwidth and Fullwidth Forms
    )


def estimate_prompt_tokens(fragments: list[str]) -> int:
    """Estimate total tokens for a list of prompt fragments."""
    return sum(estimate_tokens(f) for f in fragments)
