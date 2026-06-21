# agent/runtime/memory_write/count_cap.py
"""MemoryCountCap — enforces per-type memory limits to prevent JSONL bloat.

Runs AFTER LLM gate (or rule dedupe) as a deterministic hard limit.
Always applied regardless of gate mode.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from agent.runtime.memory_write.models import MemoryCandidate

if TYPE_CHECKING:
    from memory.store import ContextStoreAdapter

_log = logging.getLogger("memory_write.count_cap")

# Per-type max counts. When a type exceeds its limit, the lowest-confidence
# entries are evicted first (stored entries are also sorted by confidence).
MAX_PER_TYPE: dict[str, int] = {
    "task_pattern": 5,
    "artifact_summary": 20,
    "error_lesson": 10,
    "user_preference": 50,
    "tool_learning": 30,
}

# Global cap (all types combined)
MAX_TOTAL_MEMORY = 500

# Default cap for types not listed above
DEFAULT_TYPE_CAP = 15


class MemoryCountCap:
    """Enforce per-type and global memory limits.

    Works in two passes:
      1. Candidate pass: limit how many NEW entries of each type are accepted
         per batch (uses confidence sort within the batch).
      2. Storage pass: if the store already has entries exceeding the cap,
         evict lowest-confidence entries (read side).
    """

    def apply_to_candidates(
        self,
        candidates: list[MemoryCandidate],
    ) -> list[MemoryCandidate]:
        """Limit candidates by per-type caps within a single batch.

        Within each type, keeps the highest-confidence candidates up to the cap.
        Does NOT inspect storage — that's done at write time.

        Args:
            candidates: accepted candidates (already through dedupe + risk filter)

        Returns:
            candidates capped by per-type limits
        """
        if not candidates:
            return []

        # Group by type
        by_type: dict[str, list[MemoryCandidate]] = {}
        for c in candidates:
            by_type.setdefault(c.memory_type, []).append(c)

        capped: list[MemoryCandidate] = []
        for mtype, group in by_type.items():
            cap = MAX_PER_TYPE.get(mtype, DEFAULT_TYPE_CAP)
            # Sort by confidence descending, keep top N
            group.sort(key=lambda c: c.confidence, reverse=True)
            kept = group[:cap]
            capped.extend(kept)
            if len(group) > cap:
                _log.debug(
                    "CountCap: type=%s dropped %d/%d candidates (cap=%d)",
                    mtype, len(group) - cap, len(group), cap,
                )

        # Apply global cap as secondary safety
        if len(capped) > MAX_TOTAL_MEMORY:
            capped.sort(key=lambda c: c.confidence, reverse=True)
            _log.warning(
                "CountCap: global cap hit — dropped %d candidates (total=%d, limit=%d)",
                len(capped) - MAX_TOTAL_MEMORY, len(capped), MAX_TOTAL_MEMORY,
            )
            capped = capped[:MAX_TOTAL_MEMORY]

        return capped
