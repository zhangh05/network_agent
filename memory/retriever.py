# memory/retriever.py
"""Memory retriever — high-level search interface for Agent workflows."""

from typing import Optional
from memory.store import get_store


def search_memory(
    query: str,
    tags: list = None,
    project_id: str = None,
    memory_type: str = None,
    scope: str = None,
    limit: int = 10,
) -> list:
    """Search memory with full filter support."""
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


def retrieve_for_context(
    query: str,
    project_id: str = None,
    limit: int = 5,
) -> list:
    """Retrieve memory hits for agent context (no secrets in results)."""
    hits = search_memory(
        query=query,
        project_id=project_id,
        limit=limit,
    )
    # Strip secrets from returned hits
    from memory.redaction import redact_dict
    return [redact_dict(h) for h in hits]
