# agent/runtime/knowledge/retriever.py
"""KnowledgeRetrieverV2 — retrieves knowledge hits via UnifiedRetriever."""

from __future__ import annotations

from typing import Any

from agent.runtime.knowledge.models import KnowledgeHit, KnowledgeQueryPlan


class KnowledgeRetrieverV2:
    """Retrieve knowledge items using the underlying UnifiedRetriever."""

    def retrieve(self, workspace_id: str, plan: KnowledgeQueryPlan) -> list[KnowledgeHit]:
        """Execute a knowledge query plan and return typed KnowledgeHits.

        Delegates to context.unified_retriever.UnifiedRetriever for the
        actual BM25 search, then wraps results as KnowledgeHit instances.
        """
        if not plan.should_search:
            return []

        query = plan.rewritten_query or plan.query_text
        if not query.strip():
            return []

        try:
            from core.context.unified_retriever import get_retriever
            retriever = get_retriever(workspace_id)
            raw_hits = retriever.search_knowledge(query, top_k=plan.top_k)
        except Exception:
            return []

        hits: list[KnowledgeHit] = []
        for idx, h in enumerate(raw_hits, start=1):
            hit = _raw_to_knowledge_hit(h, idx)
            if hit.score >= plan.min_score:
                hits.append(hit)

        return hits


def _raw_to_knowledge_hit(h: dict[str, Any], idx: int) -> KnowledgeHit:
    """Convert a raw retriever hit dict into a KnowledgeHit."""
    return KnowledgeHit(
        source_id=h.get("source_id", ""),
        chunk_id=h.get("chunk_id", "") or h.get("item_id", ""),
        citation_id=f"K{idx}",
        title=h.get("title", ""),
        content=h.get("content", "") or h.get("index_text", "") or "",
        summary=str(h.get("summary", ""))[:200],
        score=float(h.get("_score", 0) or 0),
        source_type=h.get("source_type", ""),
        trust_level="medium",
        scan_status="pending",
        metadata={k: v for k, v in h.items() if k not in {
            "source_id", "chunk_id", "item_id", "title", "content",
            "index_text", "summary", "_score", "source_type",
        }},
    )
