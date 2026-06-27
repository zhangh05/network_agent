# agent/runtime/memory_write/dedupe.py
"""MemoryDedupe — deduplicates similar memory candidates with type-awareness.

Upgraded from prefix-only matching to:
  - Exact match across same memory_type (same type + same content = guaranteed dup)
              - Token Jaccard overlap for same type
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
    SAME_TYPE_JACCARD_THRESHOLD = 0.82   # Same type, token overlap > 82% → dup
    CROSS_TYPE_JACCARD_THRESHOLD = 0.92  # Different types, token overlap > 92% → dup

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
            threshold = self.SAME_TYPE_JACCARD_THRESHOLD if same_type else self.CROSS_TYPE_JACCARD_THRESHOLD
            similarity = _token_jaccard(c_text, ex_text)
            if similarity > threshold:
                return True

            shorter = min(len(c_text), len(ex_text))
            if shorter < 40:
                continue

            # Long near-identical paragraphs with tiny suffix edits are common;
            # keep prefix fallback only for very long content.
            overlap = _common_prefix_len(c_text, ex_text)
            if overlap / shorter > 0.95:
                return True

        return False


def _common_prefix_len(a: str, b: str) -> int:
    n = min(len(a), len(b))
    for i in range(n):
        if a[i] != b[i]:
            return i
    return n


def _token_jaccard(a: str, b: str) -> float:
    import re
    a_tokens = set(re.findall(r"[\w.-]+", a.lower()))
    b_tokens = set(re.findall(r"[\w.-]+", b.lower()))
    if not a_tokens or not b_tokens:
        return 0.0
    return len(a_tokens & b_tokens) / len(a_tokens | b_tokens)
