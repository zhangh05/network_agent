# agent/runtime/memory/retriever.py
"""MemoryRetriever — retrieves memory items via UnifiedRetriever."""

from __future__ import annotations

from typing import Any

from agent.runtime.memory.models import MemoryItem, MemoryQueryPlan
from agent.runtime.utils import from_iso, now_iso


class MemoryRetriever:
    """Retrieve memory items using the underlying UnifiedRetriever."""

    def retrieve(self, workspace_id: str, plan: MemoryQueryPlan) -> list[MemoryItem]:
        """Execute a memory query plan and return typed MemoryItems.

        Delegates to context.unified_retriever.UnifiedRetriever for the
        actual BM25 search, then wraps results as MemoryItem instances.
        """
        if not plan.should_search:
            return []

        try:
            from context.unified_retriever import get_retriever
            retriever = get_retriever(workspace_id)
            hits = retriever.search_memory(
                plan.query_text,
                top_k=plan.top_k,
            )
        except Exception:
            return []

        items: list[MemoryItem] = []
        for hit in hits:
            if not _hit_is_retrievable(hit):
                continue
            items.append(_hit_to_memory_item(hit))

        return items


def _safe_float(val: Any, default: float = 1.0) -> float:
    """Convert val to float, returning default on failure."""
    try:
        return float(val) if val is not None else default
    except (ValueError, TypeError):
        return default


def _hit_is_retrievable(hit: dict[str, Any]) -> bool:
    """Honor governance status when UnifiedRetriever returns memory docs."""
    status = str(hit.get("status") or hit.get("memory_status") or "active")
    if status != "active":
        return False
    expires_at = str(hit.get("expires_at") or "")
    if expires_at:
        try:
            if from_iso(expires_at) < from_iso(now_iso()):
                return False
        except (TypeError, ValueError):
            return False
    return True


def _hit_to_memory_item(hit: dict[str, Any]) -> MemoryItem:
    """Convert a raw retriever hit dict into a MemoryItem."""
    return MemoryItem(
        memory_id=hit.get("memory_id", "") or hit.get("item_id", ""),
        memory_type=hit.get("memory_type", "") or hit.get("item_type", ""),
        scope=hit.get("scope", "workspace"),
        content=hit.get("content", "") if isinstance(hit.get("content"), str) else str(hit.get("content", "")),
        summary=str(hit.get("summary", ""))[:200],
        confidence=_safe_float(hit.get("confidence", 1.0), 1.0),
        confirmation_status=hit.get("confirmation_status", "unconfirmed"),
        tags=list(hit.get("tags", []) or []),
        metadata={k: v for k, v in hit.items() if k not in {
            "memory_id", "item_id", "memory_type", "item_type",
            "scope", "content", "summary", "confidence",
            "confirmation_status", "tags",
        }},
    )
