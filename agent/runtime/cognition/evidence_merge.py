# agent/runtime/cognition/evidence_merge.py
"""EvidenceMerge — merges context, memory, knowledge into EvidenceBundle."""

from __future__ import annotations

from typing import Any

from agent.runtime.cognition.evidence_layers import EvidenceLayer
from agent.runtime.cognition.evidence_models import (
    EvidenceBundle,
    EvidenceItem,
    ScanReport,
)


class EvidenceMerge:
    """Merge multiple evidence sources into a unified EvidenceBundle."""

    def merge(
        self,
        context_frame: Any = None,
        memory_items: list | None = None,
        knowledge_hits: list | None = None,
        citations: list | None = None,
        scan_reports: list[ScanReport] | None = None,
    ) -> EvidenceBundle:
        """Merge all evidence sources into an EvidenceBundle with layers.

        Args:
            context_frame: ContextFrame with workspace_state, artifacts, etc.
            memory_items: List of MemoryItem from MemoryRetriever.
            knowledge_hits: List of KnowledgeHit from KnowledgeRetrieverV2.
            citations: List of Citation from CitationGraph.
            scan_reports: List of ScanReport from injection scanning.

        Returns:
            EvidenceBundle with both flat items and layer structure.
        """
        evidence = EvidenceBundle()

        # -- Context layer --
        context_layer = EvidenceLayer(
            layer_name="context",
            trust_level="high",
            policy="context_resolver",
        )
        if context_frame is not None:
            ws = getattr(context_frame, "workspace_state", None) or {}
            if ws:
                evidence.workspace_state = dict(ws)
                context_layer.items.append({"type": "workspace_state", "data": ws})

            arts = getattr(context_frame, "active_artifacts", None) or []
            if arts:
                evidence.artifact_refs = list(arts)
                for a in arts:
                    context_layer.items.append({"type": "artifact", "data": a})

        # -- Memory layer --
        memory_layer = EvidenceLayer(
            layer_name="memory",
            trust_level="low",
            policy="memory_use_policy",
        )
        if memory_items:
            for item in memory_items:
                ei = _memory_item_to_evidence(item)
                evidence.memory_items.append(ei)
                memory_layer.items.append(item)

        # -- Knowledge layer --
        knowledge_layer = EvidenceLayer(
            layer_name="knowledge",
            trust_level="medium",
            policy="source_policy",
        )
        if knowledge_hits:
            for hit in knowledge_hits:
                ei = _knowledge_hit_to_evidence(hit)
                evidence.knowledge_items.append(ei)
                knowledge_layer.items.append(hit)

        # -- Artifact layer --
        artifact_layer = EvidenceLayer(
            layer_name="artifact",
            trust_level="high",
            policy="artifact_policy",
        )
        if evidence.artifact_refs:
            artifact_layer.items = list(evidence.artifact_refs)

        # -- Citations --
        if citations:
            evidence.citations = [
                {
                    "citation_id": c.citation_id if hasattr(c, "citation_id") else c.get("citation_id", ""),
                    "source_id": c.source_id if hasattr(c, "source_id") else c.get("source_id", ""),
                    "chunk_id": c.chunk_id if hasattr(c, "chunk_id") else c.get("chunk_id", ""),
                    "title": c.title if hasattr(c, "title") else c.get("title", ""),
                    "source_type": c.source_type if hasattr(c, "source_type") else c.get("source_type", ""),
                    "evidence_type": c.evidence_type if hasattr(c, "evidence_type") else c.get("evidence_type", "knowledge"),
                }
                for c in citations
            ]

        # -- Scan reports --
        if scan_reports:
            evidence.scan_reports = list(scan_reports)

        # -- Attach layers (stored in metadata until evidence_models is updated) --
        evidence._context_layer = context_layer
        evidence._memory_layer = memory_layer
        evidence._knowledge_layer = knowledge_layer
        evidence._artifact_layer = artifact_layer

        return evidence


def _memory_item_to_evidence(item: Any) -> EvidenceItem:
    """Convert a MemoryItem to an EvidenceItem."""
    return EvidenceItem(
        evidence_id=getattr(item, "memory_id", ""),
        source_type="memory",
        trust_level="low" if getattr(item, "confirmation_status", "") != "confirmed" else "medium",
        title="",
        content=getattr(item, "content", ""),
        summary=getattr(item, "summary", ""),
        score=getattr(item, "confidence", 1.0),
        scan_status="pending",
        metadata=getattr(item, "metadata", {}),
    )


def _knowledge_hit_to_evidence(hit: Any) -> EvidenceItem:
    """Convert a KnowledgeHit to an EvidenceItem."""
    return EvidenceItem(
        evidence_id=getattr(hit, "chunk_id", ""),
        source_type="knowledge",
        trust_level=getattr(hit, "trust_level", "medium"),
        title=getattr(hit, "title", ""),
        content=getattr(hit, "content", ""),
        summary=getattr(hit, "summary", ""),
        citation_id=getattr(hit, "citation_id", ""),
        source_id=getattr(hit, "source_id", ""),
        chunk_id=getattr(hit, "chunk_id", ""),
        score=getattr(hit, "score", 0.0),
        scan_status=getattr(hit, "scan_status", "pending"),
        metadata=getattr(hit, "metadata", {}),
    )
