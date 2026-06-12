"""Unified RAG retrieval for turn context.

This layer keeps the existing knowledge module as the retrieval engine, but
orchestrates separate evidence buckets for documents and memory so one noisy
source cannot crowd out the other.
"""

from __future__ import annotations

import re
from typing import Iterable


DOCUMENT_SOURCE_TYPES = ("book", "manual", "rfc", "project_doc", "attachment")


def retrieve_context_evidence(
    workspace_id: str,
    query: str,
    *,
    doc_top_k: int = 4,
    memory_top_k: int = 3,
) -> dict:
    query = str(query or "").strip()
    if not query:
        return {
            "ok": False,
            "query": "",
            "hits": [],
            "sources": [],
            "diagnostics": {"reason": "empty_query"},
        }

    variants = _query_variants(query)
    hits = []
    diagnostics = {
        "query": query,
        "query_variants": variants,
        "retrievers": [],
        "deduplicated_count": 0,
    }

    for source_type in DOCUMENT_SOURCE_TYPES:
        bucket = _query_bucket(
            workspace_id=workspace_id,
            query_variants=variants,
            source_type=source_type,
            top_k=max(1, doc_top_k // 2),
            evidence_type="knowledge",
        )
        diagnostics["retrievers"].append(bucket["diagnostic"])
        hits.extend(bucket["hits"])

    memory_bucket = _query_bucket(
        workspace_id=workspace_id,
        query_variants=variants,
        source_type="memory",
        top_k=memory_top_k,
        evidence_type="memory",
    )
    diagnostics["retrievers"].append(memory_bucket["diagnostic"])
    hits.extend(memory_bucket["hits"])

    ranked, deduped = _rank_and_dedupe(hits)
    diagnostics["deduplicated_count"] = deduped
    sources = _source_cards(ranked)
    return {
        "ok": True,
        "query": query,
        "hits": ranked[: doc_top_k + memory_top_k],
        "sources": sources,
        "diagnostics": diagnostics,
    }


def _query_bucket(
    *,
    workspace_id: str,
    query_variants: list[str],
    source_type: str,
    top_k: int,
    evidence_type: str,
) -> dict:
    from agent.modules.knowledge.service import query_knowledge

    out = []
    backend = ""
    errors = []
    for q in query_variants:
        try:
            result = query_knowledge(
                query=q,
                workspace_id=workspace_id,
                top_k=top_k,
                filters={"source_type": source_type},
            )
        except Exception as exc:
            errors.append(str(exc)[:160])
            continue
        backend = (result.get("metadata") or {}).get("retrieval_backend", backend)
        for hit in result.get("hits") or []:
            meta = dict(hit.get("metadata") or {})
            if meta.get("source_type") != source_type:
                continue
            out.append(_normalize_hit(hit, evidence_type=evidence_type, query=q))
    return {
        "hits": out,
        "diagnostic": {
            "source_type": source_type,
            "evidence_type": evidence_type,
            "hit_count": len(out),
            "backend": backend,
            "errors": errors,
        },
    }


def _normalize_hit(hit: dict, *, evidence_type: str, query: str) -> dict:
    meta = dict(hit.get("metadata") or {})
    snippet = (
        hit.get("snippet")
        or hit.get("safe_excerpt")
        or hit.get("parent_snippet")
        or hit.get("content")
        or ""
    )
    source_type = meta.get("source_type", "")
    return {
        "chunk_id": hit.get("chunk_id", ""),
        "source_id": hit.get("source_id", ""),
        "parent_chunk_id": hit.get("parent_chunk_id", ""),
        "title": hit.get("title", ""),
        "chapter": hit.get("chapter", ""),
        "section": hit.get("section", ""),
        "safe_excerpt": str(snippet)[:900],
        "summary": hit.get("summary", ""),
        "score": float(hit.get("score", 0) or 0),
        "scope": hit.get("scope", ""),
        "source_type": source_type,
        "evidence_type": evidence_type,
        "query_variant": query,
        "memory_id": meta.get("memory_id", ""),
        "origin": meta.get("origin", ""),
    }


def _query_variants(query: str) -> list[str]:
    variants = [query]
    compact = _compact_query(query)
    if compact and compact != query:
        variants.append(compact)
    keywords = _keyword_query(query)
    if keywords and keywords not in variants:
        variants.append(keywords)
    return variants[:3]


def _compact_query(query: str) -> str:
    text = re.sub(r"[？?。！!,，；;：:]+", " ", query)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:160]


def _keyword_query(query: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9_./-]+|[\u4e00-\u9fff]{2,}", query)
    stop = {"请", "一下", "什么", "是否", "可能", "原因", "如何", "给出", "说明"}
    kept = [t for t in tokens if t.lower() not in stop and t not in stop]
    return " ".join(kept[:12])


def _rank_and_dedupe(hits: Iterable[dict]) -> tuple[list[dict], int]:
    seen = set()
    out = []
    deduped = 0
    for hit in sorted(hits, key=_rank_key):
        key = hit.get("chunk_id") or (hit.get("source_id"), hit.get("safe_excerpt", "")[:80])
        if key in seen:
            deduped += 1
            continue
        seen.add(key)
        out.append(hit)
    return out, deduped


def _rank_key(hit: dict) -> tuple:
    evidence_bias = 0 if hit.get("evidence_type") == "memory" else 1
    return (-float(hit.get("score", 0) or 0), evidence_bias, hit.get("title", ""))


def _source_cards(hits: list[dict]) -> list[dict]:
    cards = []
    for idx, hit in enumerate(hits[:8], start=1):
        prefix = "M" if hit.get("evidence_type") == "memory" else "K"
        cards.append({
            "citation_id": f"{prefix}{idx}",
            "source_id": hit.get("source_id", ""),
            "chunk_id": hit.get("chunk_id", ""),
            "title": hit.get("title", ""),
            "source_type": hit.get("source_type", ""),
            "evidence_type": hit.get("evidence_type", "knowledge"),
            "snippet": hit.get("safe_excerpt", "")[:240],
            "score": round(float(hit.get("score", 0) or 0), 3),
        })
    return cards
