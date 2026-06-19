# agent/runtime/knowledge/source_policy.py
"""SourcePolicy — evaluate knowledge retrieval quality."""

from __future__ import annotations

from typing import Any

from agent.runtime.knowledge.models import KnowledgeHit, KnowledgeQueryPlan


class SourcePolicy:
    """Evaluate knowledge retrieval results and report status."""

    def evaluate(self, hits: list[KnowledgeHit], plan: KnowledgeQueryPlan) -> dict[str, Any]:
        """Return a status dict describing retrieval quality.

        Possible statuses:
        - "empty":      No results found
        - "low_score":  Results found but all below threshold
        - "sufficient": Good results available
        """
        if not hits:
            return {
                "status": "empty",
                "count": 0,
                "strategy": plan.empty_strategy,
                "message": "No knowledge results found",
            }

        above_threshold = [h for h in hits if h.score >= plan.min_score]
        if not above_threshold:
            return {
                "status": "low_score",
                "count": len(hits),
                "max_score": max(h.score for h in hits),
                "strategy": plan.low_score_strategy,
                "message": f"All {len(hits)} results below min_score={plan.min_score}",
            }

        return {
            "status": "sufficient",
            "count": len(above_threshold),
            "max_score": max(h.score for h in above_threshold),
            "message": f"{len(above_threshold)} results above threshold",
        }
