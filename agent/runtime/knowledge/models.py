# agent/runtime/knowledge/models.py
"""Knowledge data models — KnowledgeHit, KnowledgeQueryPlan, Citation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class KnowledgeHit:
    """A single knowledge retrieval result."""

    source_id: str = ""
    chunk_id: str = ""
    citation_id: str = ""
    title: str = ""
    content: str = ""
    summary: str = ""
    score: float = 0.0
    source_type: str = ""          # "document", "manual", "kb_article"
    trust_level: str = "medium"
    scan_status: str = "pending"   # "safe", "blocked", "summary"
    conflict_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class KnowledgeQueryPlan:
    """Describes whether and how to search knowledge."""

    should_search: bool = False
    query_text: str = ""
    rewritten_query: str = ""
    top_k: int = 8
    min_score: float = 0.1
    citation_required: bool = False
    empty_strategy: str = "skip"        # "skip", "fallback", "warn"
    low_score_strategy: str = "warn"    # "include", "warn", "exclude"
    reason: str = ""


@dataclass
class Citation:
    """A citation reference linking a knowledge hit to the response."""

    citation_id: str = ""
    source_id: str = ""
    chunk_id: str = ""
    title: str = ""
    source_type: str = ""
    evidence_type: str = "knowledge"
