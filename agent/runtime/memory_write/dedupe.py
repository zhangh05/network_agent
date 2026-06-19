# agent/runtime/memory_write/dedupe.py
"""MemoryDedupe — deduplicates similar memory candidates."""

from __future__ import annotations

from agent.runtime.memory_write.models import MemoryCandidate


class MemoryDedupe:
    """Remove near-duplicate memory candidates by content similarity."""

    def dedupe(self, candidates: list[MemoryCandidate]) -> list[MemoryCandidate]:
        if len(candidates) <= 1:
            return list(candidates)
        seen: list[MemoryCandidate] = []
        for c in candidates:
            if not self._is_duplicate(c, seen):
                seen.append(c)
        return seen

    @staticmethod
    def _is_duplicate(candidate: MemoryCandidate, existing: list[MemoryCandidate]) -> bool:
        c_text = (candidate.content or "").strip().lower()
        if not c_text:
            return True
        for ex in existing:
            ex_text = (ex.content or "").strip().lower()
            if not ex_text:
                continue
            if c_text == ex_text:
                return True
            shorter = min(len(c_text), len(ex_text))
            if shorter == 0:
                continue
            overlap = _common_prefix_len(c_text, ex_text)
            if overlap / shorter > 0.85:
                return True
        return False


def _common_prefix_len(a: str, b: str) -> int:
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i
    return n
