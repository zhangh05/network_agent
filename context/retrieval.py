# context/retrieval.py
"""Unified RAG retrieval for turn context.

v3.1.0: Delegates entirely to UnifiedRetriever. No legacy knowledge service paths.
"""

from __future__ import annotations

import re
from typing import Iterable

from context.unified_retriever import get_retriever


def retrieve_context_evidence(
    workspace_id: str,
    query: str,
    *,
    doc_top_k: int = 5,
    memory_top_k: int = 3,
) -> dict:
    """Retrieve knowledge + memory evidence via UnifiedRetriever."""
    query = str(query or "").strip()
    if not query:
        return {
            "ok": False,
            "query": "",
            "hits": [],
            "sources": [],
            "diagnostics": {"reason": "empty_query"},
        }

    retriever = get_retriever(workspace_id)

    # Retrieve both buckets from unified store
    k_hits = retriever.search_knowledge(query, top_k=doc_top_k)
    m_hits = retriever.search_memory(query, top_k=memory_top_k)

    # Normalize to common hit format
    hits = []
    for h in k_hits:
        hits.append(_normalize_hit(h, evidence_type="knowledge"))
    for h in m_hits:
        hits.append(_normalize_hit(h, evidence_type="memory"))

    # Rank by score
    hits.sort(key=lambda x: -float(x.get("score", 0)))

    sources = _source_cards(hits)
    return {
        "ok": True,
        "query": query,
        "hits": hits[:doc_top_k + memory_top_k],
        "sources": sources,
        "diagnostics": {
            "engine": "unified_bm25",
            "query": query,
            "knowledge_hits": len(k_hits),
            "memory_hits": len(m_hits),
        },
    }


def _normalize_hit(hit: dict, *, evidence_type: str) -> dict:
    """Normalize a UnifiedRetriever hit to the standard format."""
    content = hit.get("content", "")
    if isinstance(content, dict):
        content = str(content)
    return {
        "chunk_id": hit.get("chunk_id", hit.get("item_id", "")),
        "source_id": hit.get("source_id", ""),
        "title": hit.get("title", ""),
        "chapter": hit.get("chapter", ""),
        "section": hit.get("section", ""),
        "content": content,
        "summary": hit.get("summary", ""),
        "score": float(hit.get("_score", 0) or 0),
        "scope": hit.get("scope", ""),
        "source_type": hit.get("source_type", ""),
        "evidence_type": evidence_type,
        "memory_id": hit.get("memory_id", ""),
    }


def _source_cards(hits: list[dict]) -> list[dict]:
    """Build citation source cards from ranked hits."""
    cards = []
    for idx, hit in enumerate(hits[:8], start=1):
        prefix = "M" if hit.get("evidence_type") == "memory" else "K"
        cards.append({
            "citation_id": f"{prefix}{idx}",
            "source_id": hit.get("source_id", ""),
            "chunk_id": hit.get("chunk_id", ""),
            "title": hit.get("title", ""),
            "source_type": hit.get("source_type", ""),
            "evidence_type": hit.get("evidence_type", "knowledge"),
            "score": round(float(hit.get("score", 0) or 0), 3),
        })
    return cards
