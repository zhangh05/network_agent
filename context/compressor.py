# context/compressor.py
"""Context compressor — limits, strips content, enforces budget."""

import json
from context.schemas import ContextItem, ContextBudget

SENSITIVE_KEYS = {"source_config", "deployable_config", "content", "file_content",
                  "report_content", "raw_prompt", "key", "token", "password",
                  "community", "secret", "private_key", "absolute_path"}


def compress_context_items(items: list, budget: ContextBudget = None,
                           mode: str = "safe_llm") -> tuple:
    budget = budget or ContextBudget()
    warnings = []

    # Enforce type limits
    counts = {}
    compressed = []
    for item in items:
        t = item.item_type
        lim = _limit_for(t, budget)
        c = counts.get(t, 0)
        if c >= lim:
            warnings.append(f"Limited {t} (max {lim})")
            continue
        counts[t] = c + 1

        # Strip sensitive keys from content
        item.content = _strip_sensitive(item.content)
        compressed.append(item)

    # Compute real budget
    total_chars = sum(len(json.dumps(i.content)) + len(i.summary) for i in compressed)
    budget.used_items = len(compressed)
    budget.used_chars = total_chars

    if total_chars > budget.max_chars:
        budget.truncated = True
        budget.truncation_reason = f"used {total_chars} > max {budget.max_chars}"
        # Drop low-priority items to fit
        while total_chars > budget.max_chars and len(compressed) > 1:
            dropped = compressed.pop()
            total_chars -= len(json.dumps(dropped.content)) + len(dropped.summary)
            warnings.append(f"Truncated {dropped.item_type} (char budget)")

        budget.used_items = len(compressed)
        budget.used_chars = total_chars

    return compressed, budget, warnings


def _limit_for(item_type: str, budget: ContextBudget) -> int:
    m = {"memory_hit": budget.max_memory_hits, "artifact_summary": budget.max_artifact_refs,
         "job_summary": budget.max_job_events, "report_summary": budget.max_report_sections,
         "knowledge_chunk": budget.max_knowledge_chunks}
    return m.get(item_type, 50)


def _strip_sensitive(obj):
    if isinstance(obj, dict):
        return {k: _strip_sensitive(v) for k, v in obj.items()
                if k not in SENSITIVE_KEYS and "path" not in k.lower()}
    if isinstance(obj, list):
        return [_strip_sensitive(i) for i in obj]
    return obj
