# memory/retriever.py
"""Memory retriever — delegates to unified ContextStore + UnifiedRetriever.

All retrieval goes through context.unified_retriever.
"""

import logging
from typing import Optional

_log = logging.getLogger("memory.retriever")


def search_memory(
    query: str,
    tags: list = None,
    workspace_id: str = None,
    memory_type: str = None,
    scope: str = None,
    limit: int = 10,
) -> list:
    """Search memory via UnifiedRetriever."""
    from context.unified_retriever import get_retriever
    ws_id = workspace_id or "default"
    retriever = get_retriever(ws_id)
    return retriever.search_memory(
        query=query,
        tags=tags,
        scope=scope,
        top_k=limit,
    )


def get_memory(memory_id: str, workspace_id: str = "default") -> Optional[dict]:
    """Get a single memory record by ID from ContextStore."""
    from context.context_store import get_context_store
    store = get_context_store(workspace_id)
    return store.get(memory_id)


def list_memory(
    scope: str = None,
    memory_type: str = None,
    workspace_id: str = None,
    limit: int = 100,
) -> list:
    """List memory records from ContextStore."""
    from context.context_store import get_context_store
    ws_id = workspace_id or "default"
    store = get_context_store(ws_id)
    return store.list_items(
        item_type="memory_hit",
        scope=scope,
        limit=limit,
    )


def retrieve_for_context(
    query: str,
    workspace_id: str = None,
    limit: int = 5,
) -> list:
    """Retrieve memory hits for agent context via UnifiedRetriever."""
    from context.unified_retriever import get_retriever
    ws_id = workspace_id or "default"
    retriever = get_retriever(ws_id)
    hits = retriever.search_memory(query, top_k=limit)
    _log.debug("Unified memory search: %d hits for '%s'", len(hits), query[:40])
    return hits
