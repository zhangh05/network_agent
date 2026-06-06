# memory/writer.py
"""Memory writer — high-level write interface for Agent workflows."""

from memory.schemas import MemoryRecord
from memory.store import get_store


def write_memory(
    title: str,
    content: str = "",
    scope: str = "short_term",
    memory_type: str = "knowledge_note",
    tags: list = None,
    project_id: str = "",
    source: str = "agent",
    confidence: float = 0.8,
    summary: str = "",
) -> str:
    record = MemoryRecord(
        scope=scope,
        memory_type=memory_type,
        title=title,
        summary=summary or content[:200],
        content=content,
        tags=tags or [],
        project_id=project_id,
        source=source,
        confidence=confidence,
    )
    store = get_store()
    return store.put(record)
