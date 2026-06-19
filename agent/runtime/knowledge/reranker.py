# agent/runtime/knowledge/reranker.py
"""KnowledgeReranker — rerank and deduplicate knowledge hits."""

from __future__ import annotations

from agent.runtime.knowledge.models import KnowledgeHit, KnowledgeQueryPlan


class KnowledgeReranker:
    """Rerank knowledge hits by score and deduplicate siblings."""

    def rerank(self, hits: list[KnowledgeHit], plan: KnowledgeQueryPlan) -> list[KnowledgeHit]:
        """Sort by score descending, deduplicate sibling chunks."""
        if not hits:
            return []

        # Sort by score descending
        ranked = sorted(hits, key=lambda h: h.score, reverse=True)

        # Deduplicate siblings (same source_id, adjacent chunk_ids)
        deduped: list[KnowledgeHit] = []
        seen_sources: dict[str, list[str]] = {}

        for hit in ranked:
            sid = hit.source_id
            cid = hit.chunk_id

            if sid and sid in seen_sources:
                existing_chunks = seen_sources[sid]
                if cid and cid in existing_chunks:
                    continue
                # Keep if not too many from same source
                if len(existing_chunks) >= 3:
                    continue
                existing_chunks.append(cid)
            elif sid:
                seen_sources[sid] = [cid]

            deduped.append(hit)

        return deduped[:plan.top_k]
