# memory/indexer.py
"""Memory indexer — now a no-op since memory writes directly to ContextStore.

v3.1.0: Memory is stored directly in ContextStore (item_type=memory_hit).
No separate knowledge projection needed. These functions are kept as
no-op stubs for any remaining callers.
"""

from __future__ import annotations
from typing import Optional


def index_memory_record(record) -> dict:
    """No-op: memory is already in ContextStore at write time."""
    data = record.as_dict() if hasattr(record, "as_dict") else dict(record or {})
    memory_id = str(data.get("memory_id", "") or data.get("item_id", ""))
    return {
        "ok": True,
        "memory_id": memory_id,
        "summary": "unified_store: no separate projection needed",
    }


def index_memory_by_id(memory_id: str) -> dict:
    """No-op: memory is already in ContextStore."""
    return {
        "ok": True,
        "memory_id": memory_id,
        "summary": "unified_store: no separate projection needed",
    }


def delete_memory_projection(memory_id: str, workspace_id: str = "") -> dict:
    """Delete memory from ContextStore."""
    if not memory_id:
        return {"ok": False, "error": "missing_memory_id", "deleted_count": 0}
    try:
        from context.context_store import get_context_store
        ws = workspace_id or "default"
        store = get_context_store(ws)
        store.delete(memory_id)
        return {"ok": True, "memory_id": memory_id, "deleted_count": 1}
    except Exception as e:
        return {"ok": False, "memory_id": memory_id, "error": str(e), "deleted_count": 0}
