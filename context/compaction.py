# context/compaction.py
"""Context compaction — prevents unbounded context growth.

Inspired by Codex's dual-limit compaction:
- auto_compact_token_limit: per-model budget (e.g. MiniMax 64k)
- full_context_window_limit: absolute model context window

Triggers:
  1. PRE-TURN: before LLM sampling, if context exceeds budget
  2. MID-TURN: during agentic loop, if tool outputs push over budget
  3. MANUAL: user-triggered via session management

Strategy: summarize old turns, keep recent turns intact.
The summary replaces the oldest N turns with a compaction message.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Model context window budgets (tokens)
MODEL_CONTEXT_BUDGETS: dict[str, int] = {
    "minimax-m3": 64000,
    "qwen": 128000,
    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,
    "default": 64000,
}

# Auto-compact at 80% of budget
COMPACT_THRESHOLD_RATIO = 0.80

# Keep at least this many recent turns intact
MIN_RECENT_TURNS = 3

# Each turn estimates ~500 tokens average
EST_TOKENS_PER_TURN = 500


def resolve_budget_for_model(model: str) -> int:
    """Get token budget for a model name."""
    model_lower = model.lower().replace(" ", "-")
    for key, budget in MODEL_CONTEXT_BUDGETS.items():
        if key in model_lower:
            return budget
    return MODEL_CONTEXT_BUDGETS["default"]


def estimate_tokens(text: str) -> int:
    """Rough token estimation: ~4 chars per token."""
    return max(1, len(text) // 4)


def should_compact(
    active_tokens: int,
    model: str = "default",
    threshold_ratio: float = COMPACT_THRESHOLD_RATIO,
) -> tuple[bool, int, int]:
    """Check if compaction is needed. Returns (needed, current_tokens, budget_limit)."""
    budget = resolve_budget_for_model(model)
    limit = int(budget * threshold_ratio)
    return active_tokens >= limit, active_tokens, limit


def compact_session_history(
    messages: list[dict],
    model: str = "default",
    min_recent: int = MIN_RECENT_TURNS,
) -> tuple[list[dict], dict]:
    """Compress session history by summarizing old turns.

    Keeps the most recent N turns intact. Summarizes everything before
    them into a single compaction message.

    Returns (compacted_messages, compaction_meta).
    """
    if len(messages) <= min_recent * 2:
        return messages, {"compacted": False, "reason": "too_few_messages"}

    # Find turn boundaries (user-assistant pairs)
    turns: list[list[dict]] = []
    current: list[dict] = []
    for msg in messages:
        if msg.get("role") == "user" and current:
            turns.append(current)
            current = []
        current.append(msg)
    if current:
        turns.append(current)

    if len(turns) <= min_recent:
        return messages, {"compacted": False, "reason": "too_few_turns"}

    # Split: old (to compact) vs recent (to keep)
    recent = turns[-min_recent:]
    old = turns[:-min_recent]

    # Build summary of old turns
    summaries = []
    for turn in old:
        user_msg = next((m.get("content", "") for m in turn if m.get("role") == "user"), "")
        assistant_msg = next((m.get("content", "") for m in turn if m.get("role") == "assistant"), "")
        summaries.append({
            "user_summary": user_msg[:200],
            "assistant_summary": assistant_msg[:200],
        })

    # Build compaction message
    compact_text = _build_compact_message(summaries)

    # Reconstruct: compaction message + recent turns
    compacted = [{"role": "system", "content": compact_text}]
    for turn in recent:
        compacted.extend(turn)

    meta = {
        "compacted": True,
        "original_turns": len(turns),
        "compacted_turns": len(old),
        "kept_turns": len(recent),
        "original_messages": len(messages),
        "compacted_messages": len(compacted),
    }

    return compacted, meta


def _build_compact_message(summaries: list[dict]) -> str:
    """Build a compaction summary for old turns."""
    if not summaries:
        return ""
    lines = [
        "[COMPACTED HISTORY] The following summarizes previous conversation turns:",
    ]
    for i, s in enumerate(summaries):
        lines.append(
            f"Turn {i+1}: "
            f"User: {s['user_summary'][:100]} | "
            f"Assistant: {s['assistant_summary'][:100]}"
        )
    lines.append(
        "[END COMPACTED HISTORY] The conversation continues below."
    )
    return "\n".join(lines)


def compact_llm_context(
    context: dict[str, Any],
    model: str = "default",
    max_budget: int | None = None,
) -> dict[str, Any]:
    """Compact LLM context to fit within budget.

    Strategies (applied in order):
    1. Truncate long text fields
    2. Limit item counts (memory hits, citations, samples)
    3. Drop least recent items

    Returns (possibly modified) context dict.
    """
    budget = max_budget or int(resolve_budget_for_model(model) * COMPACT_THRESHOLD_RATIO)
    current_size = estimate_tokens(str(context))

    if current_size <= budget:
        return context

    # Copy to avoid mutation
    compacted = dict(context)

    # Strategy 1: truncate safe_llm_context (largest field)
    if "safe_llm_context" in compacted:
        llm_ctx = compacted["safe_llm_context"]
        if isinstance(llm_ctx, dict):
            # Limit review items
            for key in ("top_review_items", "mapping_log_sample"):
                if key in llm_ctx and isinstance(llm_ctx[key], list):
                    llm_ctx[key] = llm_ctx[key][:3]

    # Strategy 2: limit memory hits
    if "memory_hits" in context:
        compacted["memory_hits"] = context["memory_hits"][:2]

    # Strategy 3: limit citations
    if "citations" in context:
        compacted["citations"] = context["citations"][:3]

    new_size = estimate_tokens(str(compacted))
    logger.debug(
        "Context compacted: %d→%d estimated tokens (budget=%d)",
        current_size, new_size, budget,
    )

    return compacted
