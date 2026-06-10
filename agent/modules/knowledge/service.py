# agent/modules/knowledge/service.py
"""Knowledge Query service — wraps the knowledge loader for the runtime.

Exposes query_knowledge() for the RuntimeLoop → ToolRouter → ToolRegistry path.
Does NOT fabricate sources. Does NOT generate fake citations.
"""

from typing import Optional


def query_knowledge(
    query: str,
    workspace_id: str = "default",
    top_k: int = 5,
    filters: Optional[dict] = None,
) -> dict:
    """Query the local knowledge/RAG store.

    Returns structured results with hits, sources, and metadata.
    Never fabricates results.

    Args:
        query: User's knowledge query string.
        workspace_id: Workspace identifier.
        top_k: Maximum number of results to return.
        filters: Optional filter criteria.

    Returns:
        dict with keys: ok, summary, query, hits, source_count,
        warnings, errors, metadata.
    """
    warnings = []
    errors = []

    if not query or not query.strip():
        return {
            "ok": False,
            "summary": "请提供查询关键词，例如: [查一下知识库里有没有 SD-WAN 资料]",
            "query": query or "",
            "hits": [],
            "source_count": 0,
            "source_summary": [],
            "warnings": [],
            "errors": ["missing_query"],
            "metadata": {},
        }

    try:
        from context.knowledge_loader import load_knowledge_context

        result = load_knowledge_context(
            user_input=query.strip(),
            workspace_id=workspace_id,
            top_k=top_k,
        )

        hits = []
        for item in result.get("results", []):
            hits.append({
                "title": item.get("title", item.get("source_name", "")),
                "content": item.get("llm_safe_content", item.get("content", ""))[:2000],
                "source": item.get("source", item.get("source_id", "")),
                "score": item.get("score"),
                "metadata": {
                    "artifact_id": item.get("artifact_id", ""),
                    "chunk_id": item.get("chunk_id", ""),
                    "source_type": item.get("source_type", ""),
                },
            })

        hit_count = len(hits)
        if hit_count == 0 and not result.get("not_found", False):
            # No results from store
            pass  # Already handled below

        if hit_count == 0:
            summary = (
                f"在知识库中未找到与 '{query}' 相关的资料。"
                "请确认知识库已配置索引，或尝试使用其他关键词查询。"
            )
        else:
            sources = [h["source"] for h in hits[:3] if h.get("source")]
            summary = (
                f"找到 {hit_count} 条与 '{query}' 相关的结果"
                + (f"，来源: {', '.join(sources)}" if sources else "")
                + "。"
            )

        source_summary = _build_source_summary(hits)

        return {
            "ok": True,
            "summary": summary,
            "query": query.strip(),
            "hits": hits,
            "source_count": hit_count,
            "source_summary": source_summary,
            "warnings": warnings,
            "errors": errors,
            "metadata": {
                "top_k": top_k,
                "workspace_id": workspace_id,
                "total_indexed": len(result.get("sources", [])),
            },
        }

    except ImportError:
        # Knowledge store not configured/available
        return {
            "ok": False,
            "summary": (
                "知识库当前不可用。知识库索引尚未配置或 knowledge 模块未安装。"
                "请联系管理员配置知识库源。"
            ),
            "query": query.strip(),
            "hits": [],
            "source_count": 0,
            "source_summary": [],
            "warnings": [],
            "errors": ["knowledge_unavailable"],
            "metadata": {},
        }
    except Exception as e:
        return {
            "ok": False,
            "summary": f"知识库查询异常: {str(e)[:200]}",
            "query": query.strip(),
            "hits": [],
            "source_count": 0,
            "source_summary": [],
            "warnings": [],
            "errors": [f"knowledge_error: {str(e)[:200]}"],
            "metadata": {},
        }


def _build_source_summary(hits: list) -> list:
    """Build lightweight source summary from hits for LLM citation."""
    if not hits:
        return []
    summaries = []
    for h in hits[:5]:
        content = h.get("content", h.get("llm_safe_content", ""))
        snippet = content[:200] if content else ""
        summaries.append({
            "title": h.get("title", ""),
            "source": h.get("source", ""),
            "score": h.get("score"),
            "snippet": snippet,
        })
    return summaries


# ── v0.8.2 — ModuleResult projection ──

def to_module_result(result: dict) -> "ModuleResult":
    """Project a v0.7.1 result dict into a standard ModuleResult.

    The result dict's keys (hits, source_count, source_summary,
    query, artifacts, warnings, errors, metadata, ok, summary) all
    become first-class ModuleResult fields:
      - data: {query, hits, source_count, source_summary}
      - artifacts: result["artifacts"]  (verbatim, if any)
      - errors / warnings / metadata: verbatim
      - ok / summary: verbatim
    """
    from agent.protocol.module_result import ModuleResult
    if not isinstance(result, dict):
        return ModuleResult.failure(
            summary="query_knowledge returned non-dict result",
            errors=["invalid_result_shape"],
        )
    ok = bool(result.get("ok", False))
    data = {
        "query": result.get("query", ""),
        "hits": list(result.get("hits") or []),
        "source_count": int(result.get("source_count", 0)),
        "source_summary": list(result.get("source_summary") or []),
    }
    if ok:
        return ModuleResult.success(
            summary=str(result.get("summary", "")),
            data=data,
            artifacts=list(result.get("artifacts") or []),
            warnings=list(result.get("warnings") or []),
            metadata=dict(result.get("metadata") or {}),
        )
    return ModuleResult.failure(
        summary=str(result.get("summary", "")),
        errors=list(result.get("errors") or ["unknown_error"]),
        warnings=list(result.get("warnings") or []),
        data=data,
        metadata=dict(result.get("metadata") or {}),
    )
