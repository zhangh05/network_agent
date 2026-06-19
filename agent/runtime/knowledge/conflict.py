# agent/runtime/knowledge/conflict.py
"""Knowledge conflict detection — thin stub for now."""

from __future__ import annotations

from agent.runtime.knowledge.models import KnowledgeHit


class KnowledgeConflictDetector:
    """Detect conflicts between knowledge hits. Stub for now."""

    def detect(self, hits: list[KnowledgeHit]) -> list[str]:
        """Return list of conflict description strings. Empty for now."""
        return []
