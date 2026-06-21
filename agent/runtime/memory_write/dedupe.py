# agent/runtime/memory_write/dedupe.py
"""MemoryDedupe — deduplicates similar memory candidates with type-awareness.

Upgraded from prefix-only matching to:
  - Exact match across same memory_type (same type + same content = guaranteed dup)
  - Prefix overlap > 85% for same type
  - Cross-type identical content still deduped (e.g., an artifact_summary and
    a task_pattern with identical content are considered one signal)
"""

from __future__ import annotations

from agent.runtime.memory_write.models import MemoryCandidate


class MemoryDedupe:
    """Remove near-duplicate memory candidates by content similarity.

    Type-aware: two entries of the same type with high overlap are more
    aggressively deduped than two entries of different types.
    """

    # Thresholds
    SAME_TYPE_PREFIX_THRESHOLD = 0.80   # Same type, prefix overlap > 80% → dup
    CROSS_TYPE_PREFIX_THRESHOLD = 0.90  # Different types, prefix overlap > 90% → dup

    def dedupe(self, candidates: list[MemoryCandidate]) -> list[MemoryCandidate]:
        if len(candidates) <= 1:
            return list(candidates)

        seen: list[MemoryCandidate] = []
        for c in candidates:
            if not self._is_duplicate(c, seen):
                seen.append(c)
        return seen

    def _is_duplicate(self, candidate: MemoryCandidate, existing: list[MemoryCandidate]) -> bool:
        c_text = (candidate.content or "").strip().lower()
        if not c_text:
            return True  # empty content → skip

        for ex in existing:
            ex_text = (ex.content or "").strip().lower()
            if not ex_text:
                continue

            # Exact match → always duplicate
            if c_text == ex_text:
                return True

            same_type = candidate.memory_type == ex.memory_type
            threshold = self.SAME_TYPE_PREFIX_THRESHOLD if same_type else self.CROSS_TYPE_PREFIX_THRESHOLD

            shorter = min(len(c_text), len(ex_text))
            if shorter == 0:
                continue

            overlap = _common_prefix_len(c_text, ex_text)
            if overlap / shorter > threshold:
                return True

        return False


def _common_prefix_len(a: str, b: str) -> int:
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i
    return n
