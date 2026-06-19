# agent/runtime/context_safe.py
"""SafeContext extraction from ContextBundle.

Keeps RAG/memory scan, audit metadata, and compaction out of the top-level
ContextBuilder orchestration.
"""

from __future__ import annotations


def safe_context_from_bundle(bundle, ctx) -> dict:
    """Extract the LLM-safe key-value context from a ContextBundle.

    Returns a flat dict suitable for safe_context injection and records scan /
    compaction decisions into ctx.metadata for trace and Inspector use.
    """
    safe = {
        "workspace_id": ctx.workspace_id,
        "session_id": ctx.session_id,
    }
    if not bundle:
        return safe

    sc = None
    if hasattr(bundle, "safe_llm_context") and bundle.safe_llm_context:
        sc = bundle.safe_llm_context
    elif hasattr(bundle, "safe_context") and bundle.safe_context:
        sc = bundle.safe_context

    if sc is not None:
        safe["intent"] = getattr(sc, "intent", "") or ""
        if hasattr(sc, "artifact_refs") and sc.artifact_refs:
            safe["artifact_refs"] = list(sc.artifact_refs)
        if hasattr(sc, "memory_hits") and sc.memory_hits:
            _inject_memory_hits(sc, safe, ctx)
        if hasattr(sc, "knowledge_hits") and sc.knowledge_hits:
            _inject_knowledge_hits(sc, safe, ctx)
        if hasattr(sc, "citations") and sc.citations:
            safe["citations"] = list(sc.citations)
        if hasattr(sc, "context_sources") and sc.context_sources:
            safe["context_sources"] = list(sc.context_sources)
        if hasattr(sc, "retrieval_diagnostics") and sc.retrieval_diagnostics:
            safe["retrieval_diagnostics"] = dict(sc.retrieval_diagnostics)
        if hasattr(sc, "warnings") and sc.warnings:
            safe["context_warnings"] = list(sc.warnings)

    if hasattr(bundle, "workspace_state") and bundle.workspace_state:
        safe["workspace_state"] = dict(bundle.workspace_state)

    ec = getattr(bundle, "execution_context", None) or getattr(bundle, "exec_context", None)
    if ec:
        safe["capability_id"] = getattr(ec, "capability_id", "") or ""
        safe["source_config_artifact_id"] = getattr(ec, "source_config_artifact_id", "") or ""

    from agent.runtime.context_compaction import auto_compact_context
    safe = auto_compact_context(safe, ctx, bundle)
    _surface_hit_counts(safe, ctx)
    return safe


def _inject_memory_hits(sc, safe: dict, ctx) -> None:
    from agent.runtime.rag_injection_scan import scan_chunks

    mem_scan = scan_chunks(list(sc.memory_hits), source="memory")
    safe["memory_hits"] = mem_scan["safe_chunks"] + mem_scan["summary_chunks"]
    scan_meta = ctx.metadata.setdefault("context_scan", {})
    scan_meta["memory"] = {
        "safe_count": len(mem_scan["safe_chunks"]),
        "summary_count": len(mem_scan["summary_chunks"]),
        "blocked_count": len(mem_scan["blocked_chunks"]),
    }
    if mem_scan["blocked_chunks"]:
        blocked_ids = [b.get("chunk_id", "") for b in mem_scan["blocked_chunks"]]
        ctx.metadata["memory_blocked_count"] = len(mem_scan["blocked_chunks"])
        ctx.metadata["memory_blocked_ids"] = blocked_ids
        ctx.metadata.setdefault("injection_warnings", []).extend(mem_scan["warnings"])


def _inject_knowledge_hits(sc, safe: dict, ctx) -> None:
    from agent.runtime.rag_injection_scan import scan_chunks

    scan_result = scan_chunks(
        list(sc.knowledge_hits),
        source="knowledge",
        source_type="knowledge",
    )
    safe["knowledge_hits"] = scan_result["safe_chunks"] + scan_result["summary_chunks"]
    blocked_count = len(scan_result["blocked_chunks"])
    summary_count = len(scan_result["summary_chunks"])
    scan_meta = ctx.metadata.setdefault("context_scan", {})
    scan_meta["knowledge"] = {
        "safe_count": len(scan_result["safe_chunks"]),
        "summary_count": summary_count,
        "blocked_count": blocked_count,
    }
    if blocked_count > 0:
        blocked_ids = [b.get("chunk_id", "") for b in scan_result["blocked_chunks"]]
        ctx.metadata["rag_blocked_count"] = blocked_count
        ctx.metadata["rag_blocked_ids"] = blocked_ids
        ctx.metadata["rag_blocked_reasons"] = [
            {"chunk_id": b.get("chunk_id"), "patterns": b.get("patterns", [])}
            for b in scan_result["blocked_chunks"]
        ]
        ctx.metadata.setdefault("injection_warnings", []).extend(scan_result["warnings"])
    if summary_count > 0:
        ctx.metadata["rag_summarized_count"] = summary_count
    if scan_result["warnings"]:
        ctx.metadata.setdefault("context_warnings", []).extend(scan_result["warnings"])


def _surface_hit_counts(safe: dict, ctx) -> None:
    try:
        mh = safe.get("memory_hits")
        kh = safe.get("knowledge_hits")
        if isinstance(mh, list):
            ctx.metadata["memory_hits_count"] = len(mh)
        if isinstance(kh, list):
            ctx.metadata["knowledge_hits_count"] = len(kh)
    except Exception:
        pass
