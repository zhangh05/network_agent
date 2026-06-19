# agent/runtime/cognition/evidence_pipeline.py
"""EvidencePipeline — wraps context_safe logic to produce EvidenceBundle.

Delegates to existing safe_context_from_bundle and injection scanning
while normalizing results into EvidenceItem/EvidenceBundle.
"""

from __future__ import annotations

from typing import Any

from agent.runtime.cognition.evidence_models import (
    EvidenceBundle,
    EvidenceItem,
    ScanReport,
)


class EvidencePipeline:
    """Build an EvidenceBundle from a ContextBundle + TurnContext."""

    def build(self, bundle, ctx) -> EvidenceBundle:
        """Produce an EvidenceBundle from a context bundle.

        Delegates the injection scan and compaction to existing helpers,
        then normalizes results into the new evidence model.
        """
        evidence = EvidenceBundle()
        if not bundle:
            return evidence

        # Delegate to the existing safe_context_from_bundle for actual scan logic
        from agent.runtime.context_safe import safe_context_from_bundle
        safe = safe_context_from_bundle(bundle, ctx)

        evidence.intent = safe.get("intent", "")
        evidence.capability_id = safe.get("capability_id", "")
        evidence.source_config_artifact_id = safe.get("source_config_artifact_id", "")

        # Normalize memory hits
        for hit in safe.get("memory_hits", []) or []:
            evidence.memory_items.append(_hit_to_evidence(hit, "memory"))

        # Normalize knowledge hits
        for hit in safe.get("knowledge_hits", []) or []:
            evidence.knowledge_items.append(_hit_to_evidence(hit, "knowledge"))

        # Passthrough fields
        if safe.get("artifact_refs"):
            evidence.artifact_refs = list(safe["artifact_refs"])
        if safe.get("workspace_state"):
            evidence.workspace_state = dict(safe["workspace_state"])
        if safe.get("citations"):
            evidence.citations = list(safe["citations"])
        if safe.get("context_sources"):
            evidence.context_sources = list(safe["context_sources"])
        if safe.get("context_warnings"):
            evidence.warnings = list(safe["context_warnings"])

        # Write hit counts into ctx.metadata
        ctx.metadata["evidence_memory_count"] = len(evidence.memory_items)
        ctx.metadata["evidence_knowledge_count"] = len(evidence.knowledge_items)

        return evidence


def _hit_to_evidence(hit: Any, source_type: str) -> EvidenceItem:
    """Convert a legacy hit dict to an EvidenceItem."""
    if not isinstance(hit, dict):
        return EvidenceItem(
            source_type=source_type,
            content=str(hit)[:500],
            scan_status="safe",
        )
    return EvidenceItem(
        evidence_id=hit.get("chunk_id", "") or hit.get("citation_id", ""),
        source_type=source_type,
        trust_level="untrusted",
        title=hit.get("title", "") or "",
        content=hit.get("content", "") or hit.get("text", "") or hit.get("snippet", "") or "",
        summary=hit.get("summary", "") or "",
        citation_id=hit.get("citation_id", "") or "",
        source_id=hit.get("source_id", "") or "",
        chunk_id=hit.get("chunk_id", "") or "",
        score=float(hit.get("score", 0) or 0),
        scan_status="safe",
        metadata={k: v for k, v in hit.items() if k not in {
            "title", "content", "text", "snippet", "summary",
            "citation_id", "source_id", "chunk_id", "score", "source_type",
        }},
    )
