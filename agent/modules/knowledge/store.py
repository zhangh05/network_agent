# agent/modules/knowledge/store.py
"""Knowledge Store — delegates to unified ContextStore.

All source records are stored as item_type="knowledge_source" in ContextStore
(items.jsonl).
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from context.context_store import get_context_store
from context.unified_retriever import get_retriever
from agent.runtime.utils import now_iso


SOURCE_ID_PREFIX = "ksrc_"
MAX_CONTENT_LENGTH = 200_000


def _now_iso() -> str:
    return now_iso()


def _generate_source_id() -> str:
    return f"{SOURCE_ID_PREFIX}{uuid.uuid4().hex[:12]}"


def _sanitize_source_label(source: str) -> str:
    """Strip local paths from source labels."""
    source = str(source or "").strip()
    if re.match(r"^[A-Za-z]:\\|^/", source):
        return re.sub(r"^.*[/\\]", "", source)
    return source[:200]


def _public_view(rec: dict, include_content: bool = False) -> dict:
    """Project a ContextStore item to the public source view."""
    meta = rec.get("metadata", {}) or {}
    out = {
        "source_id": rec.get("source_id", rec.get("item_id", "")),
        "title": rec.get("title", ""),
        "source": _sanitize_source_label(meta.get("origin_source", rec.get("source", ""))),
        "enabled": not rec.get("disabled", False),
        "deleted": rec.get("deleted", False),
        "created_at": rec.get("created_at", ""),
        "updated_at": meta.get("updated_at", rec.get("created_at", "")),
        "scope": rec.get("scope", meta.get("scope", "workspace")),
        "tags": rec.get("tags", meta.get("tags", [])),
        "metadata": {
            k: v for k, v in meta.items()
            if k not in ("content", "normalized_markdown", "origin_source")
        },
    }
    if include_content:
        out["content"] = rec.get("content", "")
        out["normalized_markdown"] = meta.get("normalized_markdown", "")
    return out


# ─── Public API ───

def import_document(
    workspace_id: str,
    title: str,
    content: str,
    source: str = "",
    metadata: dict = None,
) -> dict:
    """Import a document as a knowledge source into ContextStore."""
    content = str(content or "")
    if len(content) > MAX_CONTENT_LENGTH:
        return {
            "ok": False,
            "errors": [f"Content too large: {len(content)} > {MAX_CONTENT_LENGTH}"],
        }

    source_id = _generate_source_id()
    meta = dict(metadata or {})
    meta["origin_source"] = _sanitize_source_label(source)
    meta["updated_at"] = _now_iso()

    item = {
        "item_id": source_id,
        "item_type": "knowledge_source",
        "source": "knowledge_import",
        "source_id": source_id,
        "title": title.strip()[:200],
        "summary": content[:200],
        "content": content,
        "scope": meta.pop("scope", "workspace"),
        "sensitivity": "internal",
        "tags": meta.pop("tags", []),
        "metadata": meta,
    }

    store = get_context_store(workspace_id)
    store.put(item)

    # Also create basic chunks for searchability
    try:
        _create_basic_chunks(workspace_id, source_id, title.strip()[:200], content, meta)
    except Exception:
        pass

    return {
        "ok": True,
        "source_id": source_id,
        "title": item["title"],
        "summary": f"Imported: {item['title']} ({len(content)} chars)",
    }


def _create_basic_chunks(workspace_id: str, source_id: str, title: str, content: str, meta: dict = None):
    """Create simple chunks from content for BM25 searchability."""
    if not content or not content.strip():
        return
    meta = meta or {}
    store = get_context_store(workspace_id)
    chunk_size = 800
    overlap = 100
    text = content.strip()
    chunks = []
    i = 0
    idx = 0
    while i < len(text):
        end = min(i + chunk_size, len(text))
        chunk_text = text[i:end]
        chunk_id = f"kch_{source_id[5:]}_{idx:04d}" if source_id.startswith("ksrc_") else f"kch_{uuid.uuid4().hex[:8]}_{idx:04d}"
        chunks.append({
            "item_id": f"kc_{chunk_id}",
            "item_type": "knowledge_chunk",
            "source": "knowledge_import",
            "source_id": source_id,
            "title": title,
            "content": chunk_text,
            "chunk_id": chunk_id,
            "chunk_type": "child",
            "chunk_index": idx,
            "scope": "workspace",
            "metadata": {
                "source_type": meta.get("source_type", "document"),
                "artifact_id": meta.get("artifact_id", ""),
            },
        })
        idx += 1
        i = end - overlap if end < len(text) else end
    if chunks:
        store.put_many(chunks)


def list_sources(
    workspace_id: str,
    include_disabled: bool = False,
    include_deleted: bool = False,
) -> dict:
    """List knowledge sources."""
    store = get_context_store(workspace_id)
    items = store.list_items(item_type="knowledge_source", limit=999)

    sources = []
    for item in items:
        if item.get("deleted") and not include_deleted:
            continue
        if item.get("disabled") and not include_disabled:
            continue
        sources.append(_public_view(item))

    return {
        "ok": True,
        "sources": sources,
        "total": len(sources),
    }


def read_source(workspace_id: str, source_id: str) -> Optional[dict]:
    """Read a single source with content."""
    store = get_context_store(workspace_id)
    item = store.get(source_id)
    if not item or item.get("item_type") != "knowledge_source":
        return None
    return _public_view(item, include_content=True)


def disable_source(
    workspace_id: str, source_id: str, disabled: bool = True
) -> Optional[dict]:
    """Enable/disable a source."""
    store = get_context_store(workspace_id)
    item = store.get(source_id)
    if not item:
        return None

    # Write updated version (append-only JSONL, last wins)
    item["disabled"] = disabled
    meta = item.get("metadata", {})
    meta["updated_at"] = _now_iso()
    item["metadata"] = meta
    store.put(item)

    return _public_view(item)


def delete_source(workspace_id: str, source_id: str) -> bool:
    """Soft-delete a source and its chunks."""
    store = get_context_store(workspace_id)
    store.delete(source_id)

    # Also delete associated chunks
    chunks = store.list_items(item_type="knowledge_chunk", source_id=source_id, limit=999)
    for chunk in chunks:
        store.delete(chunk["item_id"])

    return True


def rename_source(workspace_id: str, source_id: str, title: str) -> Optional[dict]:
    """Rename a source."""
    store = get_context_store(workspace_id)
    item = store.get(source_id)
    if not item:
        return None

    item["title"] = title.strip()[:200]
    meta = item.get("metadata", {})
    meta["updated_at"] = _now_iso()
    item["metadata"] = meta
    store.put(item)

    return _public_view(item)


def query(
    workspace_id: str,
    query: str,
    top_k: int = 5,
    filters: dict = None,
) -> dict:
    """Query knowledge via UnifiedRetriever."""
    if not query or not query.strip():
        return {"ok": True, "hits": [], "total": 0}

    retriever = get_retriever(workspace_id)
    source_type = (filters or {}).get("source_type")

    # Use unified retriever for both knowledge and memory
    if source_type == "memory":
        hits = retriever.search_memory(query, top_k=top_k)
    else:
        hits = retriever.search_knowledge(query, top_k=top_k)

    # Format hits
    formatted = []
    for h in hits:
        formatted.append({
            "chunk_id": h.get("chunk_id", h.get("item_id", "")),
            "source_id": h.get("source_id", ""),
            "title": h.get("title", ""),
            "chapter": h.get("chapter", ""),
            "section": h.get("section", ""),
            "content": h.get("content", ""),
            "snippet": str(h.get("content", ""))[:300],
            "score": h.get("_score", 0),
            "scope": h.get("scope", ""),
            "metadata": h.get("metadata", {}),
        })

    return {
        "ok": True,
        "hits": formatted,
        "total": len(formatted),
        "metadata": {"retrieval_backend": "unified_bm25"},
    }


def store_stats(workspace_id: str) -> dict:
    """Return store statistics."""
    store = get_context_store(workspace_id)
    return {
        "workspace_id": workspace_id,
        "source_count": store.count(item_type="knowledge_source"),
        "chunk_count": store.count(item_type="knowledge_chunk"),
        "memory_count": store.count(item_type="memory_hit"),
        "total_items": store.count(),
        "store_version": "3.1.0",
    }
