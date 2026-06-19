# agent/runtime/cognition/evidence_pipeline.py
"""EvidencePipeline — builds EvidenceBundle directly from ContextBundle.

Reads memory/knowledge hits, artifact refs, citations, workspace state
directly from the bundle, runs injection scanning via scan_chunks,
applies ContextBudgetManager, and returns a normalized EvidenceBundle.
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

        Extracts evidence directly from the bundle, runs injection
        scanning, applies budget compaction, and normalizes results
        into the evidence model.
        """
        evidence = EvidenceBundle()
        if not bundle:
            return evidence

        # ── Extract safe_llm_context from bundle ──────────────────
        sc = None
        if hasattr(bundle, "safe_llm_context") and bundle.safe_llm_context:
            sc = bundle.safe_llm_context
        elif hasattr(bundle, "safe_context") and bundle.safe_context:
            sc = bundle.safe_context

        if sc is not None:
            evidence.intent = getattr(sc, "intent", "") or ""

            # Memory hits → scan → EvidenceItems
            if hasattr(sc, "memory_hits") and sc.memory_hits:
                self._process_memory_hits(sc, evidence, ctx)

            # Knowledge hits → scan → EvidenceItems
            if hasattr(sc, "knowledge_hits") and sc.knowledge_hits:
                self._process_knowledge_hits(sc, evidence, ctx)

            # Passthrough fields
            if hasattr(sc, "artifact_refs") and sc.artifact_refs:
                evidence.artifact_refs = list(sc.artifact_refs)
            if hasattr(sc, "citations") and sc.citations:
                evidence.citations = list(sc.citations)
            if hasattr(sc, "context_sources") and sc.context_sources:
                evidence.context_sources = list(sc.context_sources)
            if hasattr(sc, "warnings") and sc.warnings:
                evidence.warnings = list(sc.warnings)

        # ── Workspace state ───────────────────────────────────────
        if hasattr(bundle, "workspace_state") and bundle.workspace_state:
            evidence.workspace_state = dict(bundle.workspace_state)

        # ── Execution context ─────────────────────────────────────
        ec = getattr(bundle, "execution_context", None) or getattr(bundle, "exec_context", None)
        if ec:
            evidence.capability_id = getattr(ec, "capability_id", "") or ""
            evidence.source_config_artifact_id = getattr(ec, "source_config_artifact_id", "") or ""

        # ── Budget compaction ─────────────────────────────────────
        self._apply_budget(evidence, ctx, bundle)

        # ── Write hit counts into ctx.metadata ────────────────────
        ctx.metadata["evidence_memory_count"] = len(evidence.memory_items)
        ctx.metadata["evidence_knowledge_count"] = len(evidence.knowledge_items)

        return evidence

    # ── Internal helpers ──────────────────────────────────────────

    def _process_memory_hits(self, sc, evidence: EvidenceBundle, ctx) -> None:
        from agent.runtime.rag_injection_scan import scan_chunks

        mem_scan = scan_chunks(list(sc.memory_hits), source="memory")
        safe_chunks = mem_scan["safe_chunks"]
        summary_chunks = mem_scan["summary_chunks"]
        blocked_chunks = mem_scan["blocked_chunks"]

        for hit in safe_chunks + summary_chunks:
            evidence.memory_items.append(_hit_to_evidence(hit, "memory", scan_status="safe"))
        for hit in blocked_chunks:
            evidence.memory_items.append(_hit_to_evidence(hit, "memory", scan_status="blocked"))

        evidence.scan_reports.append(ScanReport(
            source="memory",
            safe_count=len(safe_chunks),
            summary_count=len(summary_chunks),
            blocked_count=len(blocked_chunks),
            blocked_ids=[b.get("chunk_id", "") for b in blocked_chunks],
            warnings=list(mem_scan.get("warnings", [])),
        ))

        # Write scan metadata for trace/Inspector compatibility
        scan_meta = ctx.metadata.setdefault("context_scan", {})
        scan_meta["memory"] = {
            "safe_count": len(safe_chunks),
            "summary_count": len(summary_chunks),
            "blocked_count": len(blocked_chunks),
        }
        if blocked_chunks:
            blocked_ids = [b.get("chunk_id", "") for b in blocked_chunks]
            ctx.metadata["memory_blocked_count"] = len(blocked_chunks)
            ctx.metadata["memory_blocked_ids"] = blocked_ids
            ctx.metadata.setdefault("injection_warnings", []).extend(mem_scan.get("warnings", []))

    def _process_knowledge_hits(self, sc, evidence: EvidenceBundle, ctx) -> None:
        from agent.runtime.rag_injection_scan import scan_chunks

        scan_result = scan_chunks(
            list(sc.knowledge_hits),
            source="knowledge",
            source_type="knowledge",
        )
        safe_chunks = scan_result["safe_chunks"]
        summary_chunks = scan_result["summary_chunks"]
        blocked_chunks = scan_result["blocked_chunks"]

        for hit in safe_chunks + summary_chunks:
            evidence.knowledge_items.append(_hit_to_evidence(hit, "knowledge", scan_status="safe"))
        for hit in blocked_chunks:
            evidence.knowledge_items.append(_hit_to_evidence(hit, "knowledge", scan_status="blocked"))

        evidence.scan_reports.append(ScanReport(
            source="knowledge",
            safe_count=len(safe_chunks),
            summary_count=len(summary_chunks),
            blocked_count=len(blocked_chunks),
            blocked_ids=[b.get("chunk_id", "") for b in blocked_chunks],
            warnings=list(scan_result.get("warnings", [])),
        ))

        # Write scan metadata for trace/Inspector compatibility
        scan_meta = ctx.metadata.setdefault("context_scan", {})
        scan_meta["knowledge"] = {
            "safe_count": len(safe_chunks),
            "summary_count": len(summary_chunks),
            "blocked_count": len(blocked_chunks),
        }
        if blocked_chunks:
            blocked_ids = [b.get("chunk_id", "") for b in blocked_chunks]
            ctx.metadata["rag_blocked_count"] = len(blocked_chunks)
            ctx.metadata["rag_blocked_ids"] = blocked_ids
            ctx.metadata["rag_blocked_reasons"] = [
                {"chunk_id": b.get("chunk_id"), "patterns": b.get("patterns", [])}
                for b in blocked_chunks
            ]
            ctx.metadata.setdefault("injection_warnings", []).extend(scan_result.get("warnings", []))
        if summary_chunks:
            ctx.metadata["rag_summarized_count"] = len(summary_chunks)
        if scan_result.get("warnings"):
            ctx.metadata.setdefault("context_warnings", []).extend(scan_result["warnings"])

    def _apply_budget(self, evidence: EvidenceBundle, ctx, bundle) -> None:
        """Apply budget compaction via ContextBudgetManager."""
        from agent.runtime.cognition.context_budget import ContextBudgetManager

        safe_dict = evidence.to_safe_context()
        safe_dict["workspace_id"] = ctx.workspace_id
        safe_dict["session_id"] = ctx.session_id
        mgr = ContextBudgetManager()
        compacted = mgr.apply(safe_dict, ctx, bundle)

        # Update evidence from compacted output (budget may have removed items)
        evidence.budget_report = mgr.last_report

        # Surface hit counts (same as context_safe._surface_hit_counts)
        mh = compacted.get("memory_hits")
        kh = compacted.get("knowledge_hits")
        if isinstance(mh, list):
            ctx.metadata["memory_hits_count"] = len(mh)
        if isinstance(kh, list):
            ctx.metadata["knowledge_hits_count"] = len(kh)


def _hit_to_evidence(hit: Any, source_type: str, scan_status: str = "safe") -> EvidenceItem:
    """Convert a legacy hit dict to an EvidenceItem."""
    if not isinstance(hit, dict):
        return EvidenceItem(
            source_type=source_type,
            content=str(hit)[:500],
            scan_status=scan_status,
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
        scan_status=scan_status,
        metadata={k: v for k, v in hit.items() if k not in {
            "title", "content", "text", "snippet", "summary",
            "citation_id", "source_id", "chunk_id", "score", "source_type",
        }},
    )
