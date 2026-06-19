# agent/runtime/cognition/evidence_models.py
"""Evidence data models — EvidenceItem, ScanReport, BudgetReport, EvidenceBundle.

These models capture normalized evidence from memory, knowledge, artifacts,
and workspace state for safe injection into the LLM prompt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvidenceItem:
    evidence_id: str = ""
    source_type: str = ""        # "memory", "knowledge", "artifact", "workspace"
    trust_level: str = "untrusted"
    title: str = ""
    content: str = ""
    summary: str = ""
    citation_id: str = ""
    source_id: str = ""
    chunk_id: str = ""
    score: float = 0.0
    scan_status: str = "pending"  # "safe", "blocked", "summary"
    blocked_reason: str = ""
    argument_source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScanReport:
    source: str = ""
    safe_count: int = 0
    summary_count: int = 0
    blocked_count: int = 0
    blocked_ids: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class BudgetReport:
    estimated_tokens: int = 0
    budget_tokens: int = 0
    threshold_tokens: int = 0
    compacted: bool = False
    decisions: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class EvidenceBundle:
    memory_items: list[EvidenceItem] = field(default_factory=list)
    knowledge_items: list[EvidenceItem] = field(default_factory=list)
    artifact_refs: list[dict[str, Any]] = field(default_factory=list)
    workspace_state: dict[str, Any] = field(default_factory=dict)
    citations: list[dict[str, Any]] = field(default_factory=list)
    context_sources: list[str] = field(default_factory=list)
    scan_reports: list[ScanReport] = field(default_factory=list)
    budget_report: BudgetReport | None = None
    intent: str = ""
    capability_id: str = ""
    source_config_artifact_id: str = ""
    warnings: list[str] = field(default_factory=list)

    # Layered evidence structure (Phase 3)
    context_layer: Any = None     # EvidenceLayer
    memory_layer: Any = None      # EvidenceLayer
    knowledge_layer: Any = None   # EvidenceLayer
    artifact_layer: Any = None    # EvidenceLayer

    # Conflict and trust metadata
    conflicts: list[Any] = field(default_factory=list)
    trust_report: dict[str, Any] = field(default_factory=dict)
    citation_graph: list[Any] = field(default_factory=list)

    def by_source(self, source_type: str) -> list[EvidenceItem]:
        """Return evidence items filtered by source_type."""
        if source_type == "memory":
            return self.memory_items
        if source_type == "knowledge":
            return self.knowledge_items
        return [
            item
            for items in (self.memory_items, self.knowledge_items)
            for item in items
            if item.source_type == source_type
        ]

    def to_safe_context(self) -> dict[str, Any]:
        """Produce a dict compatible with the existing safe_context format.

        Keys: memory_hits, knowledge_hits, workspace_state, artifact_refs,
        citations, context_sources, intent, capability_id, etc.
        """
        safe: dict[str, Any] = {}
        if self.intent:
            safe["intent"] = self.intent
        if self.capability_id:
            safe["capability_id"] = self.capability_id
        if self.source_config_artifact_id:
            safe["source_config_artifact_id"] = self.source_config_artifact_id

        if self.memory_items:
            safe["memory_hits"] = [
                _evidence_to_hit(item) for item in self.memory_items
                if item.scan_status != "blocked"
            ]
        if self.knowledge_items:
            safe["knowledge_hits"] = [
                _evidence_to_hit(item) for item in self.knowledge_items
                if item.scan_status != "blocked"
            ]
        if self.artifact_refs:
            safe["artifact_refs"] = list(self.artifact_refs)
        if self.workspace_state:
            safe["workspace_state"] = dict(self.workspace_state)
        if self.citations:
            safe["citations"] = list(self.citations)
        if self.context_sources:
            safe["context_sources"] = list(self.context_sources)
        if self.warnings:
            safe["context_warnings"] = list(self.warnings)
        if self.conflicts:
            safe["evidence_conflicts"] = [
                {
                    "conflict_type": getattr(c, "conflict_type", ""),
                    "description": getattr(c, "description", ""),
                    "severity": getattr(c, "severity", "warning"),
                }
                for c in self.conflicts
            ]
        if self.trust_report and self.trust_report.get("adjustments"):
            safe["trust_warnings"] = [
                f"{a['source_type']}:{a['item_id']} trust {a['from']}→{a['to']}"
                for a in self.trust_report.get("adjustments", [])
            ]
        return safe


def _evidence_to_hit(item: EvidenceItem) -> dict[str, Any]:
    """Convert an EvidenceItem to the legacy hit dict format."""
    hit: dict[str, Any] = {}
    if item.title:
        hit["title"] = item.title
    if item.content:
        hit["content"] = item.content
    if item.summary:
        hit["summary"] = item.summary
    if item.source_id:
        hit["source_id"] = item.source_id
    if item.chunk_id:
        hit["chunk_id"] = item.chunk_id
    if item.citation_id:
        hit["citation_id"] = item.citation_id
    if item.score:
        hit["score"] = item.score
    if item.source_type:
        hit["source_type"] = item.source_type
    hit.update(item.metadata)
    return hit
