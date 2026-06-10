# agent/modules/knowledge/service.py
"""Knowledge service — v1.0.

Exposes:
  - query_knowledge(query, workspace_id, top_k, filters)  (uses store)
  - import_document(workspace_id, title, content, source, metadata)
  - list_sources(workspace_id, include_disabled, include_deleted)
  - read_source(workspace_id, source_id)
  - disable_source(workspace_id, source_id, disabled)
  - delete_source(workspace_id, source_id)
  - to_module_result(result_dict)        (v0.8.2 standard projection)

v1.0 design:
  - The service is a thin adapter over the workspace knowledge store
    (KnowledgeStore, JSONL-backed, no external DB).
  - When the store has no enabled sources, the service returns
    ok=True, source_count=0, hits=[], source_summary=[] — never
    fabricates.
  - The legacy context.knowledge_loader is consulted ONLY when the
    store is empty AND the legacy loader is available; results are
    merged and de-duplicated. This keeps the v0.7.1 capability tests
    passing (they exercise the legacy loader path) while letting
    v1.0 callers import + query their own data.
"""

from __future__ import annotations

from typing import Optional


# ── Re-export store functions for callers (service is the public face) ──

def import_document(workspace_id: str, title: str, content: str,
                     source: str = "", metadata: Optional[dict] = None) -> dict:
    """Service adapter: imports a document into the workspace knowledge store.

    Returns a dict with ok / summary / source (full record view) /
    source_id (top-level shortcut) / errors / warnings.
    """
    from agent.modules.knowledge.store import import_document as _impl
    result = _impl(workspace_id=workspace_id, title=title, content=content,
                   source=source, metadata=metadata)
    # Surface source_id at the top level for handler convenience.
    if isinstance(result, dict) and "source" in result:
        result["source_id"] = result["source"].get("source_id", "")
    return result


def list_sources(workspace_id: str, include_disabled: bool = False,
                  include_deleted: bool = False) -> dict:
    """Service adapter: list source records (no content).

    Returns a v0.8.2-friendly dict with ok / sources / count / errors.
    """
    from agent.modules.knowledge.store import list_sources as _impl
    items = _impl(workspace_id=workspace_id, include_disabled=include_disabled,
                 include_deleted=include_deleted)
    return {
        "ok": True,
        "summary": f"Listed {len(items)} source(s)",
        "sources": items,
        "count": len(items),
        "errors": [],
        "warnings": [],
    }


def read_source(workspace_id: str, source_id: str) -> dict:
    """Service adapter: full record (incl. content) or ok=False on miss."""
    from agent.modules.knowledge.store import read_source as _impl
    rec = _impl(workspace_id=workspace_id, source_id=source_id)
    if rec is None:
        return {
            "ok": False,
            "summary": f"source not found: {source_id}",
            "source_id": source_id,
            "errors": ["source_not_found"],
            "warnings": [],
        }
    return {
        "ok": True,
        "summary": f"Read {rec.get('source_id', '')}",
        "source_id": rec.get("source_id", ""),
        "source": rec,
        "errors": [],
        "warnings": [],
    }


def disable_source(workspace_id: str, source_id: str,
                    disabled: bool = True) -> dict:
    """Service adapter: toggle soft-disable flag."""
    from agent.modules.knowledge.store import disable_source as _impl
    rec = _impl(workspace_id=workspace_id, source_id=source_id,
                disabled=disabled)
    if rec is None:
        return {
            "ok": False,
            "summary": f"source not found: {source_id}",
            "source_id": source_id,
            "errors": ["source_not_found"],
            "warnings": [],
        }
    return {
        "ok": True,
        "summary": f"Source {source_id} disabled={disabled}",
        "source_id": source_id,
        "source": rec,
        "errors": [],
        "warnings": [],
    }


def delete_source(workspace_id: str, source_id: str) -> dict:
    """Service adapter: soft-delete a source (audit trail kept)."""
    from agent.modules.knowledge.store import delete_source as _impl
    ok = _impl(workspace_id=workspace_id, source_id=source_id)
    if not ok:
        return {
            "ok": False,
            "summary": f"source not found: {source_id}",
            "source_id": source_id,
            "errors": ["source_not_found"],
            "warnings": [],
        }
    return {
        "ok": True,
        "summary": f"Source {source_id} soft-deleted",
        "source_id": source_id,
        "errors": [],
        "warnings": [],
    }


# ── query_knowledge ──

def query_knowledge(
    query: str,
    workspace_id: str = "default",
    top_k: int = 5,
    filters: Optional[dict] = None,
) -> dict:
    """Query the workspace knowledge store.

    v1.0 flow:
      1. Try the new KnowledgeStore (token-overlap scoring).
      2. If the store has enabled sources but no hits, return
         ok=True with source_count=0 (no fabrication).
      3. If the store is completely empty, optionally fall back to
         the legacy context.knowledge_loader (if installed). This is
         the v0.7.1 compatibility path; the legacy result is
         returned verbatim — never merged with fabricated hits.
      4. If the store is unavailable AND the legacy loader is also
         unavailable, return ok=False, knowledge_unavailable.
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

    from agent.modules.knowledge.store import (
        store_stats, query as _store_query,
    )

    workspace_id = workspace_id or "default"
    stats = store_stats(workspace_id)

    # Path 1: store has enabled sources — answer from the store.
    if stats["enabled_count"] > 0:
        result = _store_query(
            workspace_id=workspace_id, query=query.strip(),
            top_k=top_k, filters=filters,
        )
        result.setdefault("metadata", {})
        result["metadata"]["retrieval_backend"] = "local_store"
        return result

    # Path 2: store is empty — fall back to legacy loader (v0.7.1 path).
    try:
        from context.knowledge_loader import load_knowledge_context
        legacy = load_knowledge_context(
            user_input=query.strip(),
            workspace_id=workspace_id,
            top_k=top_k,
        )
        hits = []
        for item in legacy.get("results", []):
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
        if hits:
            sources = [h["source"] for h in hits[:3] if h.get("source")]
            summary = (
                f"找到 {len(hits)} 条与 '{query}' 相关的结果"
                + (f"，来源: {', '.join(sources)}" if sources else "")
                + "。"
            )
        else:
            summary = (
                f"在知识库中未找到与 '{query}' 相关的资料。"
                "请确认知识库已配置索引，或尝试使用其他关键词查询。"
            )
        source_summary = _build_source_summary(hits)
        return {
            "ok": True,
            "summary": summary,
            "query": query.strip(),
            "hits": hits,
            "source_count": len(hits),
            "source_summary": source_summary,
            "warnings": warnings,
            "errors": errors,
            "metadata": {
                "retrieval_backend": "legacy_loader",
                "workspace_id": workspace_id,
                "top_k": top_k,
            },
        }
    except ImportError:
        # No store content, no legacy loader.
        return {
            "ok": True,
            "summary": (
                f"知识库中未找到与 '{query}' 相关的结果。"
                "请先调用 knowledge.import_document 导入资料，"
                "或联系管理员配置知识库源。"
            ),
            "query": query.strip(),
            "hits": [],
            "source_count": 0,
            "source_summary": [],
            "warnings": ["store_empty", "legacy_loader_unavailable"],
            "errors": [],
            "metadata": {
                "retrieval_backend": "local_store",
                "workspace_id": workspace_id,
                "top_k": top_k,
            },
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
            "metadata": {"retrieval_backend": "local_store"},
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
    """Project a v0.7.1 / v1.0 result dict into a standard ModuleResult.

    The result dict's keys (hits, source_count, source_summary,
    query, source_id, source, artifacts, warnings, errors, metadata,
    ok, summary) all become first-class ModuleResult fields:
      - data: {query, hits, source_count, source_summary,
              source_id, source}    (v1.0 added source_id/source)
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
    if "source_id" in result:
        data["source_id"] = result.get("source_id", "")
    if "source" in result:
        data["source"] = result.get("source", "")
    if "sources" in result:
        data["sources"] = list(result.get("sources") or [])
    if "count" in result:
        data["count"] = int(result.get("count", 0))
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
