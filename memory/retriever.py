# memory/retriever.py
"""Memory retriever — high-level search interface for Agent workflows."""

from memory.store import get_store


def search_memory(query: str, tags: list = None, scope: str = None, limit: int = 10) -> list:
    store = get_store()
    return store.search(query, tags=tags, limit=limit)


def get_memory(memory_id: str) -> dict | None:
    store = get_store()
    record = store.get(memory_id)
    return record.as_dict() if record else None


def list_memory(scope: str = None, memory_type: str = None) -> list:
    store = get_store()
    return store.list(scope=scope, memory_type=memory_type)
