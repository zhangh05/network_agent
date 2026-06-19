# agent/runtime/memory_write/writer.py
"""MemoryWriter — stub writer that records intent without real persistence.

This module generates MemoryWritePlan only. Real persistence is deferred
to a future integration with the ContextStore / Memory subsystem.
"""

from __future__ import annotations

from agent.runtime.memory_write.models import MemoryWritePlan


class MemoryWriter:
    """Record memory write intent. Does NOT persist to real storage."""

    def write(self, ctx, plan: MemoryWritePlan) -> dict:
        """Accept a plan and return a summary. No real DB write."""
        return {
            "status": "planned",
            "candidate_count": len(plan.candidates),
            "skipped_count": len(plan.skipped),
            "message": "Memory write planned but not persisted (deferred to integration phase)",
        }
