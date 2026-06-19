# agent/runtime/knowledge/query_planner.py
"""KnowledgeQueryPlanner — decides whether to search knowledge based on scene."""

from __future__ import annotations

import re
from typing import Any

from agent.runtime.knowledge.models import KnowledgeQueryPlan


# Filler words to strip from queries (Chinese + English)
_CJK_FILLER = re.compile(
    r"(请问|请帮我|帮我|帮忙|可以|能不能|能否|告诉我|我想知道|我想了解)",
)
_EN_FILLER = re.compile(
    r"\b(please|could you|can you|tell me|i want to know|help me)\b",
    re.IGNORECASE,
)


def _rewrite_query(query: str) -> str:
    """Strip filler words from the query for better retrieval."""
    if not query:
        return query
    cleaned = _CJK_FILLER.sub("", query)
    cleaned = _EN_FILLER.sub("", cleaned)
    # Collapse whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned if cleaned else query


class KnowledgeQueryPlanner:
    """Plan knowledge retrieval based on scene decision and context frame."""

    def plan(self, scene_decision: Any, context_frame: Any = None) -> KnowledgeQueryPlan:
        """Produce a KnowledgeQueryPlan.

        Knowledge task -> should_search=True, citation_required=True.
        Simple chat -> should_search=False.
        """
        if scene_decision is None:
            return KnowledgeQueryPlan(reason="no scene_decision")

        is_simple = getattr(scene_decision, "is_simple_chat", False)
        if is_simple:
            return KnowledgeQueryPlan(
                should_search=False,
                reason="simple_chat: no knowledge search",
            )

        is_knowledge = getattr(scene_decision, "is_knowledge_task", False)
        needs_knowledge = getattr(scene_decision, "needs_knowledge", False)
        is_factual = getattr(scene_decision, "is_factual_query", False)
        user_input = getattr(scene_decision, "user_input", "")

        if is_knowledge or needs_knowledge or is_factual:
            query_text = user_input
            if context_frame is not None:
                query_text = getattr(context_frame, "user_input", "") or user_input

            rewritten = _rewrite_query(query_text)

            return KnowledgeQueryPlan(
                should_search=True,
                query_text=query_text,
                rewritten_query=rewritten,
                top_k=8,
                min_score=0.1,
                citation_required=is_knowledge,
                empty_strategy="warn" if is_knowledge else "skip",
                low_score_strategy="warn",
                reason="knowledge search required by scene",
            )

        return KnowledgeQueryPlan(
            should_search=False,
            reason="knowledge not needed for this scene",
        )
