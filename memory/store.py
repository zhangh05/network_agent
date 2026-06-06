# memory/store.py
"""Memory store factory. Returns the active memory backend."""

from memory.backends.jsonl_store import JSONLMemoryStore
from memory.backends.sqlite_store import SQLiteMemoryStore


# Singleton — use JSONL backend by default
_store: JSONLMemoryStore | None = None


def get_store() -> JSONLMemoryStore:
    global _store
    if _store is None:
        _store = JSONLMemoryStore()
    return _store
