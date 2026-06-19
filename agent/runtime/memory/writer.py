# agent/runtime/memory/writer.py
"""MemoryWriter — stub for writing memory entries."""

from __future__ import annotations

from agent.runtime.memory.models import MemoryItem, MemoryWritePlan


class MemoryWriter:
    """Write memory entries to the store. Stub for now."""

    def write(self, workspace_id: str, plan: MemoryWritePlan) -> MemoryItem | None:
        """Write a memory entry based on the write plan.

        Returns the created MemoryItem, or None if write was skipped.
        """
        if not plan.should_write:
            return None
        # Stub: actual persistence TBD
        return MemoryItem(
            memory_type=plan.memory_type,
            scope=plan.scope,
            content=plan.content,
            confirmation_status="unconfirmed" if plan.requires_confirmation else "confirmed",
        )
