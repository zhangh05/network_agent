# agent/runtime/context_compaction.py
"""Context budget estimation and auto-compaction helpers."""

from __future__ import annotations


def estimate_tokens(text: str) -> int:
    """Rough token estimation: ~4 chars per token for CJK+EN mixed text."""
    if not text:
        return 0
    return max(1, len(text) // 4)


def estimate_context_tokens(safe_context: dict) -> int:
    """Estimate total tokens for a safe_context dict."""
    import json
    try:
        text = json.dumps(safe_context, ensure_ascii=False)
        return estimate_tokens(text)
    except Exception:
        return len(str(safe_context)) // 4


def estimate_history_tokens(history_window: list) -> int:
    """Estimate tokens for history window."""
    import json
    try:
        total = 0
        for h in history_window:
            if hasattr(h, "content"):
                total += estimate_tokens(str(h.content))
            elif isinstance(h, dict):
                total += estimate_tokens(json.dumps(h, ensure_ascii=False))
        return total
    except Exception:
        return len(str(history_window)) // 4


def auto_compact_context(safe_context: dict, ctx, bundle) -> dict:
    """Auto-compact safe_context when it exceeds the model budget.

    Applies layered compression in priority order:
      1. trim_history     — drop oldest 2 turns while keeping >=2 most recent
      2. drop_low_score   — keep top knowledge chunks
      3. summarize_memory — replace memory hits with compact summaries
      4. drop_extras      — remove workspace_state/citations/diagnostics

    The decisions are written into ctx.metadata so Inspector/trace can explain
    why context changed.
    """
    try:
        model = ctx.model_config.get("model", "") if ctx.model_config else ""
        from context.schemas import resolve_budget_for_model
        budget = resolve_budget_for_model(model)
        budget_tokens = budget.max_chars // 4 if budget.max_chars else 3000
    except Exception:
        budget_tokens = 3000

    estimated = estimate_context_tokens(safe_context)
    threshold = int(budget_tokens * 0.85)

    ctx.metadata.setdefault("context_budget", {
        "estimated_tokens": estimated,
        "budget_tokens": budget_tokens,
        "threshold_tokens": threshold,
    })

    if estimated <= threshold:
        return safe_context

    compacted = dict(safe_context)
    ctx.metadata["auto_compact"] = True
    ctx.metadata["compact_pre_tokens"] = estimated
    decisions = ctx.metadata.setdefault("compact_decisions", [])

    if len(ctx.history_window) > 2:
        before = len(ctx.history_window)
        keep = max(2, len(ctx.history_window) - 2)
        ctx.history_window = ctx.history_window[-keep:]
        after = len(ctx.history_window)
        decisions.append({"layer": "trim_history", "before": before, "after": after})
        ctx.metadata["compact_layer"] = "trim_history"
        ctx.metadata["compact_history_before"] = before
        ctx.metadata["compact_history_after"] = after
        post = estimate_context_tokens(compacted) + estimate_history_tokens(ctx.history_window)
        if post <= threshold:
            ctx.metadata["compact_post_tokens"] = post
            return compacted

    knowledge_hits = compacted.get("knowledge_hits", [])
    if isinstance(knowledge_hits, list) and len(knowledge_hits) > 1:
        scored = []
        for k in knowledge_hits:
            score = k.get("score", 0) if isinstance(k, dict) else 0
            scored.append((score, k))
        scored.sort(key=lambda x: x[0], reverse=True)
        keep_count = max(1, min(3, len(scored)))
        compacted["knowledge_hits"] = [k for _, k in scored[:keep_count]]
        decisions.append({"layer": "drop_low_score", "before": len(knowledge_hits), "after": keep_count})
        ctx.metadata["compact_layer"] = "drop_low_score"
        ctx.metadata["compact_knowledge_before"] = len(knowledge_hits)
        ctx.metadata["compact_knowledge_after"] = keep_count
        if estimate_context_tokens(compacted) <= threshold:
            ctx.metadata["compact_post_tokens"] = estimate_context_tokens(compacted)
            return compacted

    memory_hits = compacted.get("memory_hits", [])
    if isinstance(memory_hits, list) and len(memory_hits) > 1:
        summaries = []
        for m in memory_hits:
            if isinstance(m, dict):
                title = m.get("title", "") or m.get("summary", "") or ""
                summaries.append(title[:80])
        if summaries:
            compacted["memory_hits"] = [{"summary": " | ".join(summaries)[:500]}]
            decisions.append({"layer": "summarize_memory", "before": len(memory_hits), "after": 1})
            ctx.metadata["compact_layer"] = "summarize_memory"
            ctx.metadata["compact_memory_before"] = len(memory_hits)
            if estimate_context_tokens(compacted) <= threshold:
                ctx.metadata["compact_post_tokens"] = estimate_context_tokens(compacted)
                return compacted

    dropped = []
    for k in ("workspace_state", "citations", "retrieval_diagnostics", "context_sources"):
        if k in compacted:
            dropped.append(k)
            compacted.pop(k, None)
    decisions.append({"layer": "drop_extras", "dropped": dropped})
    ctx.metadata["compact_layer"] = "drop_extras"
    ctx.metadata["compact_post_tokens"] = estimate_context_tokens(compacted)
    return compacted
