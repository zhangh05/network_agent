# agent/runtime/knowledge/citation.py
"""CitationGraph — builds citations from knowledge hits."""

from __future__ import annotations

from agent.runtime.knowledge.models import Citation, KnowledgeHit


class CitationGraph:
    """Build citation references from knowledge hits."""

    def build(self, hits: list[KnowledgeHit]) -> list[Citation]:
        """Build a list of Citation objects from knowledge hits."""
        citations: list[Citation] = []
        seen: set[str] = set()

        for hit in hits:
            if hit.scan_status == "blocked":
                continue
            cid = hit.citation_id or hit.chunk_id
            if cid in seen:
                continue
            seen.add(cid)

            citations.append(Citation(
                citation_id=hit.citation_id,
                source_id=hit.source_id,
                chunk_id=hit.chunk_id,
                title=hit.title,
                source_type=hit.source_type,
                evidence_type="knowledge",
            ))

        return citations
