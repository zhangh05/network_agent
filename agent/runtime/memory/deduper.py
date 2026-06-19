# agent/runtime/memory/deduper.py
"""MemoryDeduper — stub for deduplicating memory entries."""

from __future__ import annotations

from agent.runtime.memory.models import MemoryItem


class MemoryDeduper:
    """Deduplicate memory items. Stub for now."""

    def dedup(self, items: list[MemoryItem]) -> list[MemoryItem]:
        """Remove duplicate memory items by memory_id."""
        if not items:
            return []
        seen: set[str] = set()
        result: list[MemoryItem] = []
        for item in items:
            key = item.memory_id or item.content[:100]
            if key not in seen:
                seen.add(key)
                result.append(item)
        return result
