# agent/runtime/cognition/evidence_pipeline.py
"""EvidencePipeline — builds EvidenceBundle via the layered pipeline.

Pipeline order:
  ContextQueryPlanner.plan → ContextResolver.resolve →
  MemoryQueryPlanner.plan → MemoryRetriever.retrieve →
  KnowledgeQueryPlanner.plan → KnowledgeRetrieverV2.retrieve →
  KnowledgeReranker.rerank → CitationGraph.build →
  EvidenceMerge.merge → scan_evidence →
  EvidenceConflictDetector.detect → TrustPolicy.apply →
  ContextBudgetManager.apply
"""

from __future__ import annotations

from typing import Any

from agent.runtime.cognition.evidence_models import (
    EvidenceBundle,
    EvidenceItem,
    ScanReport,
)


class EvidencePipeline:
    """Build an EvidenceBundle from TurnContext via the full pipeline."""

    def build(self, ctx, services=None) -> EvidenceBundle:
        """Produce an EvidenceBundle by running each pipeline stage.

        Args:
            ctx:      TurnContext with workspace_id, scene_decision, etc.
            services: Optional service container (unused today, reserved).

        Returns:
            Fully populated EvidenceBundle.
        """
        from agent.runtime.context.query_plan import ContextQueryPlanner
        from agent.runtime.context.resolver import ContextResolver
        from agent.runtime.memory.query_planner import MemoryQueryPlanner
        from agent.runtime.memory.retriever import MemoryRetriever
        from agent.runtime.knowledge.query_planner import KnowledgeQueryPlanner
        from agent.runtime.knowledge.retriever import KnowledgeRetrieverV2
        from agent.runtime.knowledge.reranker import KnowledgeReranker
        from agent.runtime.knowledge.citation import CitationGraph
        from agent.runtime.cognition.evidence_merge import EvidenceMerge
        from agent.runtime.cognition.evidence_conflict import EvidenceConflictDetector
        from agent.runtime.cognition.trust_policy import TrustPolicy
        from agent.runtime.cognition.context_budget import ContextBudgetManager

        scene = getattr(ctx, "scene_decision", None)
        workspace_id = getattr(ctx, "workspace_id", "") or ""

        # ── 1. ContextQueryPlanner.plan ──────────────────────────────
        context_planner = ContextQueryPlanner()
        context_query_plan = context_planner.plan(scene, ctx)

        # ── 2. ContextResolver.resolve ───────────────────────────────
        resolver = ContextResolver()
        context_frame = resolver.resolve(ctx, context_query_plan)

        # ── 3. MemoryQueryPlanner.plan ───────────────────────────────
        mem_planner = MemoryQueryPlanner()
        memory_query_plan = mem_planner.plan(scene, context_frame)

        # ── 4. MemoryRetriever.retrieve ──────────────────────────────
        mem_retriever = MemoryRetriever()
        memory_items = mem_retriever.retrieve(workspace_id, memory_query_plan)

        # ── 5. KnowledgeQueryPlanner.plan ────────────────────────────
        know_planner = KnowledgeQueryPlanner()
        knowledge_query_plan = know_planner.plan(scene, context_frame)

        # ── 6. KnowledgeRetrieverV2.retrieve ─────────────────────────
        know_retriever = KnowledgeRetrieverV2()
        knowledge_hits = know_retriever.retrieve(workspace_id, knowledge_query_plan)

        # ── 7. KnowledgeReranker.rerank ──────────────────────────────
        reranker = KnowledgeReranker()
        knowledge_hits = reranker.rerank(knowledge_hits, knowledge_query_plan)

        # ── 8. CitationGraph.build ───────────────────────────────────
        citation_graph = CitationGraph()
        citations = citation_graph.build(knowledge_hits)

        # ── 9. EvidenceMerge.merge ───────────────────────────────────
        merger = EvidenceMerge()
        evidence = merger.merge(
            context_frame=context_frame,
            memory_items=memory_items,
            knowledge_hits=knowledge_hits,
            citations=citations,
        )

        # ── 10. scan_evidence ────────────────────────────────────────
        self._scan_evidence(evidence, ctx)

        # ── 11. EvidenceConflictDetector.detect ──────────────────────
        detector = EvidenceConflictDetector()
        evidence.conflicts = detector.detect(evidence)

        # ── 12. TrustPolicy.apply ────────────────────────────────────
        policy = TrustPolicy()
        evidence.trust_report = policy.apply(evidence, ctx)

        # ── 13. ContextBudgetManager.apply ───────────────────────────
        budget_mgr = ContextBudgetManager()
        budget_mgr.apply(evidence, ctx)
        evidence.budget_report = budget_mgr.last_report

        # ── Write metadata ───────────────────────────────────────────
        ctx.metadata["context_query_plan"] = _plan_to_dict(context_query_plan)
        ctx.metadata["memory_query_plan"] = _plan_to_dict(memory_query_plan)
        ctx.metadata["knowledge_query_plan"] = _plan_to_dict(knowledge_query_plan)
        ctx.metadata["evidence_conflicts"] = [
            {
                "conflict_type": getattr(c, "conflict_type", ""),
                "description": getattr(c, "description", ""),
                "severity": getattr(c, "severity", "warning"),
            }
            for c in evidence.conflicts
        ]
        ctx.metadata["trust_report"] = evidence.trust_report
        ctx.metadata["evidence_memory_count"] = len(evidence.memory_items)
        ctx.metadata["evidence_knowledge_count"] = len(evidence.knowledge_items)
        ctx.metadata["safe_context_status"] = "ok"

        # Surface hit counts (non-blocked items only)
        ctx.metadata["memory_hits_count"] = len([
            i for i in evidence.memory_items if i.scan_status != "blocked"
        ])
        ctx.metadata["knowledge_hits_count"] = len([
            i for i in evidence.knowledge_items if i.scan_status != "blocked"
        ])

        # ── Set ctx.context_frame ────────────────────────────────────
        ctx.context_frame = context_frame

        return evidence

    # ── Internal helpers ──────────────────────────────────────────

    def _scan_evidence(self, evidence: EvidenceBundle, ctx) -> None:
        """Scan memory and knowledge items for prompt injection."""
        from agent.runtime.rag_injection_scan import scan_chunk

        # -- Memory scan --
        safe_mem, summary_mem, blocked_mem = 0, 0, 0
        blocked_mem_ids: list[str] = []
        mem_warnings: list[str] = []
        for item in evidence.memory_items:
            result = scan_chunk(
                item.content, chunk_id=item.evidence_id, source="memory",
            )
            if result.blocked:
                item.scan_status = "blocked"
                item.blocked_reason = str(result.matched_patterns)
                blocked_mem += 1
                blocked_mem_ids.append(item.evidence_id)
                mem_warnings.append(
                    f"BLOCKED memory {item.evidence_id}: {result.matched_patterns}"
                )
            elif result.summary_only:
                item.scan_status = "summary"
                item.content = item.summary or item.content[:300]
                summary_mem += 1
                mem_warnings.append(
                    f"SUMMARIZED memory {item.evidence_id}: {result.matched_patterns}"
                )
            else:
                item.scan_status = "safe"
                safe_mem += 1

        if evidence.memory_items:
            evidence.scan_reports.append(ScanReport(
                source="memory",
                safe_count=safe_mem,
                summary_count=summary_mem,
                blocked_count=blocked_mem,
                blocked_ids=blocked_mem_ids,
                warnings=mem_warnings,
            ))

        # -- Knowledge scan (source_type="knowledge" → relaxed patterns) --
        safe_k, summary_k, blocked_k = 0, 0, 0
        blocked_k_ids: list[str] = []
        k_warnings: list[str] = []
        for item in evidence.knowledge_items:
            result = scan_chunk(
                item.content, chunk_id=item.evidence_id,
                source="knowledge", source_type="knowledge",
            )
            if result.blocked:
                item.scan_status = "blocked"
                item.blocked_reason = str(result.matched_patterns)
                blocked_k += 1
                blocked_k_ids.append(item.evidence_id)
                k_warnings.append(
                    f"BLOCKED knowledge {item.evidence_id}: {result.matched_patterns}"
                )
            elif result.summary_only:
                item.scan_status = "summary"
                item.content = item.summary or item.content[:300]
                summary_k += 1
                k_warnings.append(
                    f"SUMMARIZED knowledge {item.evidence_id}: {result.matched_patterns}"
                )
            else:
                item.scan_status = "safe"
                safe_k += 1

        if evidence.knowledge_items:
            evidence.scan_reports.append(ScanReport(
                source="knowledge",
                safe_count=safe_k,
                summary_count=summary_k,
                blocked_count=blocked_k,
                blocked_ids=blocked_k_ids,
                warnings=k_warnings,
            ))

        # -- Write scan metadata for trace/Inspector compatibility --
        scan_meta = ctx.metadata.setdefault("context_scan", {})
        scan_meta["memory"] = {
            "safe_count": safe_mem,
            "summary_count": summary_mem,
            "blocked_count": blocked_mem,
        }
        scan_meta["knowledge"] = {
            "safe_count": safe_k,
            "summary_count": summary_k,
            "blocked_count": blocked_k,
        }
        if blocked_mem:
            ctx.metadata["memory_blocked_count"] = blocked_mem
            ctx.metadata["memory_blocked_ids"] = blocked_mem_ids
            ctx.metadata.setdefault("injection_warnings", []).extend(mem_warnings)
        if blocked_k:
            ctx.metadata["rag_blocked_count"] = blocked_k
            ctx.metadata["rag_blocked_ids"] = blocked_k_ids
            ctx.metadata["rag_blocked_reasons"] = [
                {"chunk_id": cid, "patterns": []}
                for cid in blocked_k_ids
            ]
            ctx.metadata.setdefault("injection_warnings", []).extend(k_warnings)
        if summary_k:
            ctx.metadata["rag_summarized_count"] = summary_k
        if k_warnings:
            ctx.metadata.setdefault("context_warnings", []).extend(k_warnings)


def _plan_to_dict(plan) -> dict:
    """Convert a dataclass plan to a plain dict for metadata storage."""
    if hasattr(plan, "__dataclass_fields__"):
        return {k: getattr(plan, k) for k in plan.__dataclass_fields__}
    return {}
