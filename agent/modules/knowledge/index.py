# agent/modules/knowledge/index.py
"""BM25 lexical index for v1.0.1.

Spec § 5: "首期 lexical 使用 SQLite FTS5 或 BM25。"

We use a pure-Python BM25 (no SQLite FTS5 dependency) so the index is:
  - inspectable (we can show what was indexed)
  - portable (no DB engine to ship)
  - test-friendly (deterministic + in-process)
  - tunable (k1, b, scope boost)

Layout (per workspace):
  {ws_root}/{workspace_id}/knowledge/
      sources.jsonl            (v1.0 source store)
      chunks.jsonl             (v1.0.1 chunks: parents + children)
      index.meta.json          (last_build_at, chunk_count, scope_count)
"""

from __future__ import annotations

import json
import math
import re
import threading
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from agent.modules.knowledge.schemas import (
    KnowledgeChunk, KnowledgeSource, SCOPE_PRIORITY,
)


# Tunable BM25 params (Robertson / Lucene defaults).
BM25_K1 = 1.2
BM25_B = 0.75

# Scope boost: per-scope multiplicative score bonus.
SCOPE_BOOST = {"session": 1.30, "workspace": 1.10, "global": 1.00}

_TOKEN_RE = re.compile(r"[\w一-鿿]+", re.UNICODE)
_HIT_SNIPPET_MAX = 200


def _ws_root() -> Path:
    try:
        import workspace.manager as wm
        return wm.WS_ROOT
    except Exception:
        from artifacts.store import _get_ws_root
        return _get_ws_root()


def _index_meta_path(workspace_id: str) -> Path:
    return _ws_root() / workspace_id / "knowledge" / "index.meta.json"


def _chunks_path(workspace_id: str) -> Path:
    return _ws_root() / workspace_id / "knowledge" / "chunks.jsonl"


# ── BM25 core ──

class BM25Index:
    """Pure-Python BM25 over a list of pre-tokenized documents.

    Each document is a KnowledgeChunk; we score on its `index_text`
    (which already encodes title/chapter/section + body).
    """

    def __init__(self):
        self.docs: List[KnowledgeChunk] = []
        self.doc_tokens: List[List[str]] = []
        self.doc_lens: List[int] = []
        self.df: Counter = Counter()      # term -> document frequency
        self.avg_dl: float = 0.0
        self.N: int = 0

    def fit(self, docs: List[KnowledgeChunk]) -> "BM25Index":
        self.docs = list(docs)
        self.doc_tokens = [_tokenize(d.index_text) for d in docs]
        self.doc_lens = [len(t) for t in self.doc_tokens]
        self.N = len(self.docs)
        self.avg_dl = (sum(self.doc_lens) / self.N) if self.N else 0.0
        self.df = Counter()
        for tokens in self.doc_tokens:
            for term in set(tokens):
                self.df[term] += 1
        return self

    def score(self, query: str) -> List[Tuple[int, float, dict]]:
        """Return [(doc_idx, score, score_meta), ...] sorted desc by score.

        score_meta exposes:
          - lexical_score (raw BM25)
          - semantic_score: null (placeholder, not enabled in v1.0.1)
          - final_score:    score * scope_boost
          - scope:          chunk's scope
        """
        if self.N == 0 or not query.strip():
            return []
        q_tokens = _tokenize(query)
        if not q_tokens:
            return []
        scores = [0.0] * self.N
        for q in q_tokens:
            df = self.df.get(q, 0)
            if df == 0:
                continue
            idf = math.log(1 + (self.N - df + 0.5) / (df + 0.5))
            for i, tokens in enumerate(self.doc_tokens):
                tf = tokens.count(q)
                if tf == 0:
                    continue
                dl = self.doc_lens[i]
                norm = 1 - BM25_B + BM25_B * (dl / max(self.avg_dl, 1e-6))
                scores[i] += idf * (tf * (BM25_K1 + 1)) / (tf + BM25_K1 * norm)
        out = []
        for i, s in enumerate(scores):
            if s <= 0:
                continue
            scope = (self.docs[i].metadata or {}).get("scope", "workspace")
            boost = SCOPE_BOOST.get(scope, 1.0)
            final = s * boost
            out.append((i, s, {
                "lexical_score": round(s, 4),
                "semantic_score": None,
                "final_score": round(final, 4),
                "scope": scope,
            }))
        out.sort(key=lambda x: (-x[2]["final_score"], -x[2]["lexical_score"]))
        return out


def _tokenize(s: str) -> List[str]:
    return [t.lower() for t in _TOKEN_RE.findall(str(s or ""))]


def _snippet_from_text(text: str, query: str) -> str:
    text = str(text or "")
    if not text:
        return ""
    if not query.strip():
        return text[:_HIT_SNIPPET_MAX]
    q_tokens = _tokenize(query)
    lower = text.lower()
    for tok in q_tokens:
        idx = lower.find(tok.lower())
        if idx >= 0:
            start = max(0, idx - 60)
            end = min(len(text), start + _HIT_SNIPPET_MAX)
            return text[start:end]
    return text[:_HIT_SNIPPET_MAX]


# ── Chunk store (JSONL, per-workspace) ──

_chunk_locks: dict[str, threading.RLock] = {}
_chunk_locks_guard = threading.Lock()


def _chunk_lock(workspace_id: str) -> threading.RLock:
    with _chunk_locks_guard:
        lock = _chunk_locks.get(workspace_id)
        if lock is None:
            lock = threading.RLock()
            _chunk_locks[workspace_id] = lock
        return lock


def save_chunks(workspace_id: str, chunks: List[KnowledgeChunk]) -> int:
    """Append chunks to the workspace chunk store. Returns count saved."""
    if not workspace_id:
        return 0
    with _chunk_lock(workspace_id):
        path = _chunks_path(workspace_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            for c in chunks:
                f.write(json.dumps(c.to_dict(), ensure_ascii=False) + "\n")
        _touch_meta(workspace_id)
    return len(chunks)


def replace_chunks(workspace_id: str, source_id: str,
                    new_chunks: List[KnowledgeChunk]) -> int:
    """Replace all chunks for a source_id (used by reindex)."""
    if not workspace_id or not source_id:
        return 0
    with _chunk_lock(workspace_id):
        path = _chunks_path(workspace_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = []
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        if isinstance(d, dict) and d.get("source_id") != source_id:
                            existing.append(d)
                    except Exception:
                        continue
        for c in new_chunks:
            existing.append(c.to_dict())
        tmp = path.with_suffix(".jsonl.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            for d in existing:
                f.write(json.dumps(d, ensure_ascii=False) + "\n")
        tmp.replace(path)
        _touch_meta(workspace_id)
    return len(new_chunks)


def _touch_meta(workspace_id: str) -> None:
    p = _index_meta_path(workspace_id)
    n = 0
    cp = _chunks_path(workspace_id)
    if cp.exists():
        with open(cp, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    n += 1
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "workspace_id": workspace_id,
        "chunk_count": n,
        "last_build_at": datetime.now(timezone.utc).isoformat(),
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def load_all_chunks(workspace_id: str) -> List[KnowledgeChunk]:
    if not workspace_id:
        return []
    with _chunk_lock(workspace_id):
        path = _chunks_path(workspace_id)
        if not path.exists():
            return []
        out = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    if isinstance(d, dict):
                        out.append(KnowledgeChunk.from_dict(d))
                except Exception:
                    continue
        return out


def list_chunks(
    workspace_id: str,
    source_id: str = "",
    chunk_type: str = "",
    limit: int = 200,
) -> List[dict]:
    """Return lightweight public view of chunks (no full content)."""
    out = []
    for c in load_all_chunks(workspace_id):
        if source_id and c.source_id != source_id:
            continue
        if chunk_type and c.chunk_type != chunk_type:
            continue
        out.append({
            "chunk_id": c.chunk_id,
            "source_id": c.source_id,
            "parent_chunk_id": c.parent_chunk_id,
            "chunk_type": c.chunk_type,
            "chapter": c.chapter,
            "section": c.section,
            "subsection": c.subsection,
            "page_start": c.page_start,
            "page_end": c.page_end,
            "chunk_index": c.chunk_index,
            "token_count": c.token_count,
            "metadata": dict(c.metadata or {}),
        })
    out.sort(key=lambda x: (x["source_id"], x["chunk_index"]))
    return out[:limit] if limit else out


def get_chunk(workspace_id: str, chunk_id: str) -> Optional[KnowledgeChunk]:
    for c in load_all_chunks(workspace_id):
        if c.chunk_id == chunk_id:
            return c
    return None


# ── Search / retrieval ──

def search_chunks(
    workspace_id: str,
    query: str,
    top_k: int = 5,
    scope: str = "",
    source_id: str = "",
    source_type: str = "",
    tags: Optional[List[str]] = None,
    chapter: str = "",
) -> dict:
    """Search child chunks only.

    Filtering order:
      1. enabled-only (chunks belonging to enabled sources)
      2. scope filter (if given)
      3. source_id / source_type / chapter / tags filters
      4. BM25 lexical scoring
      5. scope boost
    Returns:
      {
        ok, summary, query, hits (children only),
        source_count, scope, scoring metadata
      }
    """
    if not workspace_id or not query.strip():
        return {
            "ok": False,
            "summary": "workspace_id and query are required",
            "errors": ["missing_inputs"],
            "hits": [], "source_count": 0, "source_summary": [],
        }
    top_k = int(top_k or 5)
    if top_k < 1:
        top_k = 1
    tags = tags or []

    # Load enabled sources first (cross-check enabled flag).
    from agent.modules.knowledge.store import list_sources as _list_sources
    enabled_source_ids = {s["source_id"] for s in
                          _list_sources(workspace_id=workspace_id)
                          if s.get("enabled", True)
                          and not s.get("deleted", False)}

    all_chunks = load_all_chunks(workspace_id)
    children = [c for c in all_chunks if c.chunk_type == "child"
                and c.source_id in enabled_source_ids]
    if scope:
        children = [c for c in children
                    if (c.metadata or {}).get("scope") == scope]
    if source_id:
        children = [c for c in children if c.source_id == source_id]
    if source_type:
        children = [c for c in children
                    if (c.metadata or {}).get("source_type") == source_type]
    if chapter:
        children = [c for c in children if (c.chapter or "") == chapter]
    if tags:
        wanted = set(t.lower() for t in tags)
        children = [c for c in children
                    if any(t.lower() in wanted
                           for t in (c.metadata or {}).get("tags") or [])]

    if not children:
        return {
            "ok": True,
            "summary": (
                f"知识库中未找到与 '{query}' 相关的命中。"
                "请检查 scope / source_id 过滤，或先 import_file。"
            ),
            "query": query,
            "hits": [], "source_count": 0, "source_summary": [],
            "errors": [],
            "warnings": [],
            "metadata": _scoring_meta(workspace_id, "no_candidates"),
        }
    idx = BM25Index().fit(children)
    ranked = idx.score(query)[:top_k]
    hits = []
    for doc_idx, lex, meta in ranked:
        c = children[doc_idx]
        hits.append({
            "chunk_id": c.chunk_id,
            "source_id": c.source_id,
            "parent_chunk_id": c.parent_chunk_id,
            "title": (c.metadata or {}).get("source_title", ""),
            "chapter": c.chapter,
            "section": c.section,
            "page_start": c.page_start,
            "page_end": c.page_end,
            "snippet": _snippet_from_text(c.content, query),
            "score": meta["final_score"],
            "lexical_score": meta["lexical_score"],
            "semantic_score": meta["semantic_score"],
            "scope": meta["scope"],
            "metadata": {
                "chunk_type": c.chunk_type,
                "source_type": (c.metadata or {}).get("source_type", ""),
            },
        })
    summaries = []
    for h in hits[:5]:
        summaries.append({
            "chunk_id": h["chunk_id"],
            "title": h["title"],
            "chapter": h["chapter"],
            "section": h["section"],
            "page_start": h["page_start"],
            "score": h["score"],
            "snippet": h["snippet"][:_HIT_SNIPPET_MAX],
        })
    if hits:
        summary = (
            f"找到 {len(hits)} 条与 '{query}' 相关的结果"
            + (f"，来源: {', '.join(h['title'] for h in hits[:3] if h['title'])}"
               if hits else "")
            + "。"
        )
    else:
        summary = (
            f"知识库中未找到与 '{query}' 相关的结果。"
            "请确认已导入相关资料，或尝试其他关键词。"
        )
    return {
        "ok": True,
        "summary": summary,
        "query": query,
        "hits": hits,
        "source_count": len(hits),
        "source_summary": summaries,
        "errors": [],
        "warnings": [],
        "metadata": _scoring_meta(workspace_id, "bm25_v1"),
    }


def _scoring_meta(workspace_id: str, scoring: str) -> dict:
    return {
        "retrieval_backend": "local_bm25",
        "scoring": scoring,
        "scoring_version": "v1",
        "lexical_score_present": True,
        "semantic_score_present": False,
        "semantic_status": "not_enabled",
        "scope_priority": list(SCOPE_PRIORITY.keys()),
        "workspace_id": workspace_id,
    }
