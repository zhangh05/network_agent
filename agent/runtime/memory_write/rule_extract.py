# agent/runtime/memory_write/rule_extract.py
"""Pure-rule memory extraction — no LLM, zero extra cost.

Used when workspace memory_gating is set to "rule_only".
"""
from __future__ import annotations

import re
from typing import Any


# Skip these generic tool outputs — they carry no meaningful info
_GENERIC = {"", "started", "completed", "ok", "true", "false", "success", "failed", "done", "finish", "finished"}

# Also skip if the summary is just a generic verb with punctuation
_GENERIC_PREFIXES = ("completed", "started", "finished", "success", "failed", "ok", "done", "running", "executed")


def _normalize_summary(text: str) -> str:
    """Strip punctuation and lowercase for robust generic detection."""
    s = str(text or "").strip().lower()
    # Strip trailing punctuation (e.g. "Completed." → "completed")
    s = s.rstrip(".。!！?？,，;；")
    return s


def _is_generic(text: str) -> bool:
    normalized = _normalize_summary(text)
    if not normalized:
        return True
    if normalized in _GENERIC:
        return True
    # Check if the first word is a generic verb (e.g. "Completed successfully" → "completed")
    first_word = normalized.split()[0] if normalized else ""
    if first_word in _GENERIC_PREFIXES and len(normalized) <= len(first_word) + 3:
        return True
    return False


def _extract_summary(result: Any) -> str:
    """Pull a meaningful snippet from a tool result dict/object."""
    if result is None:
        return ""
    if isinstance(result, dict):
        # Prefer pre-computed summary/message, then dig into data
        for k in ("summary", "message", "output", "result", "content", "text", "stdout"):
            v = result.get(k)
            if v and isinstance(v, str) and not _is_generic(v):
                return v[:200]
        data = result.get("data")
        if isinstance(data, str) and not _is_generic(data):
            return data[:200]
        if isinstance(data, dict):
            for k in ("output", "result", "content", "text", "stdout", "message", "summary"):
                v = data.get(k)
                if v and isinstance(v, str) and not _is_generic(v):
                    return v[:200]
    elif isinstance(result, str) and not _is_generic(result):
        return result[:200]
    return ""


def extract_memories_rule_only(
    user_input: str,
    assistant_response: str,
    tool_calls: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Extract memory items deterministically from a completed turn.

    No LLM is called. Only structured rule-based extraction.

    Args:
        user_input: the user's original message
        assistant_response: the LLM's final response
        tool_calls: list of tool call dicts (tool_id, summary, result, ok, ...)

    Returns:
        list of {content, type, confidence} items
    """
    items: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    def _add(content: str, memory_type: str, confidence: float) -> None:
        text = str(content or "").strip()
        if len(text) < 10:
            return
        key = text[:80]
        if key in seen_keys:
            return
        seen_keys.add(key)
        items.append({
            "content": text[:2000],
            "type": memory_type,
            "confidence": confidence,
        })

    # ── 1. Extract from tool_calls (operational facts) ──
    for tc in tool_calls:
        if not isinstance(tc, dict):
            continue
        tool_id = str(tc.get("tool_id") or tc.get("tool") or "")
        if not tc.get("ok", True):
            # Failed tool → error lesson
            err = _extract_summary(tc.get("result"))
            if err:
                _add(f"{tool_id}: {err}" if tool_id else err, "error_lesson", 0.6)
            continue
        # Successful → operational fact
        summary = _extract_summary(tc.get("result"))
        if summary:
            payload = f"{tool_id}: {summary}" if tool_id else summary
            _add(payload, "operational_fact", 0.7)

    # ── 2. Detect user preferences from input text ──
    # Pattern: "用X格式", "以后X", "always use X", "我喜欢X"
    pref_patterns = [
        r"用[^，。.!?.]+格式",  # 用Markdown格式
        r"以[^，。.!?.]+方式",  # 以简洁方式
        r"以[^，。.!?.]+形式",  # 以表格形式
        r"以后[^，。.!?.]+",   # 以后都用中文
        r"always\s+use\s+[^.\n]+",
        r"i\s+prefer\s+[^.\n]+",
    ]
    for pat in pref_patterns:
        m = re.search(pat, user_input, re.IGNORECASE)
        if m:
            _add(m.group(0).strip(), "user_preference", 0.5)
            break  # only one preference per turn

    # ── 3. Cap at 3 items (matches llm_memory.py) ──
    return items[:3]
