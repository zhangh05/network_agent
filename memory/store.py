# memory/store.py
"""Memory store factory — wraps unified ContextStore.

All data lives in ContextStore. This module is the MemoryStore facade for
callers that import get_store().
"""

import threading

from context.context_store import get_context_store


class _DictWithAsDict(dict):
    """Dict subclass with as_dict() for record-style callers."""
    def as_dict(self):
        return dict(self)


class ContextStoreAdapter:
    """Adapter that wraps ContextStore with the MemoryStore API."""

    def __init__(self, workspace_id: str = "default"):
        self._store = get_context_store(workspace_id)
        self.workspace_id = workspace_id

    def put(self, record) -> str:
        """Write a memory record. Accepts MemoryRecord or dict."""
        if hasattr(record, "as_dict"):
            data = record.as_dict()
        else:
            data = dict(record)

        item = {
            "item_id": data.get("memory_id", ""),
            "item_type": "memory_hit",
            "source": data.get("source", "agent"),
            "source_id": data.get("source", ""),
            "title": data.get("title", ""),
            "summary": data.get("summary", ""),
            "content": data.get("content", ""),
            "scope": data.get("scope", "workspace"),
            "sensitivity": data.get("sensitivity", "internal"),
            "tags": data.get("tags", []),
            "memory_id": data.get("memory_id", ""),
            "memory_type": data.get("memory_type", ""),
            "confidence": data.get("confidence", ""),
            "project_id": data.get("project_id", ""),
            "expires_at": data.get("expires_at", ""),
            "metadata": data.get("metadata", {}),
            "redaction_applied": data.get("redaction_applied", False),
        }
        return self._store.put(item)

    def get(self, memory_id: str):
        """Get a memory record by ID."""
        item = self._store.get(memory_id)
        if item is None:
            # Try with mem_ prefix
            item = self._store.get(f"mem_{memory_id}")
        if item is None:
            return None
        return _DictWithAsDict(item)

    def search(self, query: str = "", tags=None, project_id=None,
               memory_type=None, scope=None, limit=10) -> list:
        """Search memory items."""
        from context.unified_retriever import get_retriever
        retriever = get_retriever(self.workspace_id)
        return retriever.search_memory(query, tags=tags, scope=scope, top_k=limit)

    def list(self, scope=None, memory_type=None, project_id=None,
             limit=100) -> list:
        """List memory items."""
        return self._store.list_items(
            item_type="memory_hit",
            scope=scope,
            limit=limit,
        )

    def delete(self, memory_id: str) -> bool:
        """Delete a memory item."""
        return self._store.delete(memory_id)

    def count(self, project_id=None) -> int:
        """Count memory items."""
        return self._store.count(item_type="memory_hit")

    def cleanup_expired(self, dry_run=False) -> dict:
        """Clean up expired items."""
        return self._store.cleanup_expired(dry_run=dry_run)

    def compact(self) -> dict:
        """Compact the store."""
        return self._store.compact()


_stores: dict[str, ContextStoreAdapter] = {}
_stores_lock = threading.Lock()


def get_store(workspace_id: str = "default") -> ContextStoreAdapter:
    """Return the ContextStore-backed MemoryStore facade."""
    with _stores_lock:
        store = _stores.get(workspace_id)
        if store is None:
            store = ContextStoreAdapter(workspace_id)
            _stores[workspace_id] = store
        return store
