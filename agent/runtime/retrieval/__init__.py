# agent/runtime/retrieval/__init__.py
"""Retrieval — proactive trigger policy and unknown feedback.

P1-B: Production-grade retrieval strategy.
  - RetrievalTriggerPolicy: determines when memory/knowledge/file-evidence
    retrieval is required, optional, or skippable.
  - UnknownFeedback: structured miss reporting (miss_reason + next_action).
  - RetrievalDecision: unified output, written into the per-turn Decision Report.
"""

from agent.runtime.retrieval.trigger_policy import (
    RetrievalTriggerPolicy,
    RetrievalDecision,
    RetrievalStatus,
)
from agent.runtime.retrieval.unknown_feedback import (
    UnknownFeedback,
    MISS_REASONS,
    NEXT_ACTIONS,
)

__all__ = [
    "RetrievalTriggerPolicy",
    "RetrievalDecision",
    "RetrievalStatus",
    "UnknownFeedback",
    "MISS_REASONS",
    "NEXT_ACTIONS",
]
