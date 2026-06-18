# memory/retriever.py
"""Memory retriever — high-level search interface for Agent workflows.

v3.0.0: BM25 RAG primary path with JSONL keyword fallback.
"""

import logging
from typing import Optional
from memory.store import get_store

_log = logging.getLogger("memory.retriever")


def search_memory(
    query: str,
    tags: list = None,
    project_id: str = None,
    memory_type: str = None,
    scope: str = None,
    limit: int = 10,
) -> list:
    """Search memory with full filter support (JSONL keyword matching)."""
    store = get_store()
    return store.search(
        query=query,
        tags=tags,
        project_id=project_id,
        memory_type=memory_type,
        scope=scope,
        limit=limit,
    )


def get_memory(memory_id: str) -> Optional[dict]:
    """Get a single memory record by ID."""
    store = get_store()
    record = store.get(memory_id)
    return record.as_dict() if record else None


def list_memory(
    scope: str = None,
    memory_type: str = None,
    project_id: str = None,
    limit: int = 100,
) -> list:
    """List memory records with optional filters."""
    store = get_store()
    return store.list(
        scope=scope,
        memory_type=memory_type,
        project_id=project_id,
        limit=limit,
    )


# ═══════════════════════════════════════════════════════════════════════
# v3.0.0: BM25 RAG retrieval
# ═══════════════════════════════════════════════════════════════════════

def _bm25_search_memory(query: str, workspace_id: str, limit: int = 5) -> list:
    """Search memory projections through the BM25 knowledge index.

    Memory records are projected into the knowledge store by memory/indexer.py
    at write time (source_type="memory", metadata.hidden=True).

    Returns list of dicts with keys: memory_id, title, summary, content, score, chunk_id.
    On any error, returns empty list (caller falls back to JSONL search).
    """
    try:
        from agent.modules.knowledge.index import search_chunks
        result = search_chunks(
            workspace_id=workspace_id,
            query=query,
            top_k=limit * 2,  # request more to allow post-filtering
            source_type="memory",
        )
        if not result or not result.get("ok"):
            return []

        hits = result.get("hits", []) or result.get("results", []) or []
        memory_hits = []
        seen = set()

        for h in hits:
            if isinstance(h, dict):
                meta = h.get("metadata", {}) or {}
                mid = meta.get("memory_id", "") or h.get("memory_id", "")
                if not mid or mid in seen:
                    continue
                seen.add(mid)
                memory_hits.append({
                    "memory_id": mid,
                    "title": h.get("title", "") or meta.get("source_title", ""),
                    "summary": h.get("summary", "") or h.get("chapter", ""),
                    "content": h.get("safe_excerpt", "") or h.get("content", ""),
                    "score": h.get("score", 0) or h.get("lexical_score", 0),
                    "chunk_id": h.get("chunk_id", ""),
                    "source_id": h.get("source_id", ""),
                    "memory_type": meta.get("memory_type", ""),
                    "memory_scope": meta.get("memory_scope", ""),
                    "confidence": meta.get("memory_confidence", ""),
                })
        return memory_hits[:limit]
    except Exception as e:
        _log.debug("BM25 memory search failed, will fall back to JSONL: %s", e)
        return []


def _merge_memory_hits(bm25_hits: list, jsonl_hits: list, limit: int = 5) -> list:
    """Merge BM25 and JSONL memory hits, deduplicating by summary similarity.

    BM25 hits take priority (higher quality scoring). JSONL hits fill gaps.
    """
    from memory.redaction import redact_dict

    merged = []
    seen_ids = set()

    # BM25 results first (higher quality)
    for h in bm25_hits:
        mid = h.get("memory_id", "")
        if mid:
            seen_ids.add(mid)
        merged.append(redact_dict(h))

    # JSONL results fill remaining slots
    for h in jsonl_hits:
        mid = h.get("memory_id", "")
        if mid and mid in seen_ids:
            continue
        safe = redact_dict(h)
        # Deduplicate by title containment
        title = (safe.get("title", "") or "").lower()
        is_dup = False
        for existing in merged:
            ext_title = (existing.get("title", "") or "").lower()
            if title and ext_title and (title in ext_title or ext_title in title):
                is_dup = True
                break
        if not is_dup:
            merged.append(safe)

    return merged[:limit]


def retrieve_for_context(
    query: str,
    project_id: str = None,
    limit: int = 5,
) -> list:
    """v3.0.0: Retrieve memory hits for agent context.

    Primary path: BM25 RAG search through knowledge index (memory projections).
    Fallback: JSONL keyword search.

    All results are redacted — no secrets leak into context.
    """
    workspace_id = project_id or "default"

    # 1. Try BM25 RAG search (memory projections in knowledge index)
    bm25_hits = _bm25_search_memory(query, workspace_id, limit=limit)
    if bm25_hits:
        _log.debug("BM25 memory search: %d hits for '%s'", len(bm25_hits), query[:40])

    # 2. Get JSONL keyword hits for fallback/merge
    jsonl_hits = search_memory(
        query=query,
        project_id=project_id,
        limit=limit,
    )

    # 3. Merge, deduplicate, redact
    if bm25_hits:
        merged = _merge_memory_hits(bm25_hits, jsonl_hits, limit=limit)
        _log.debug("Memory merged: BM25=%d + JSONL=%d → %d final",
                   len(bm25_hits), len(jsonl_hits), len(merged))
        return merged

    # BM25 not available — fall back to JSONL only
    from memory.redaction import redact_dict
    return [redact_dict(h) for h in jsonl_hits[:limit]]
