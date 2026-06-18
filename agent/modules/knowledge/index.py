# agent/modules/knowledge/index.py
"""BM25 lexical index for v1.0.2 (Retrieval Quality & Evaluation).

Spec § 5: "首期 lexical 使用 SQLite FTS5 或 BM25。"

v1.0.2 improvements over v1.0.1:
  - CJK 2-gram + 3-gram tokenization in addition to word tokens
  - Field weights: title / chapter / section / tags > body
  - Configurable BM25 k1 / b
  - Deterministic query expansion (network terms) — no LLM
  - Sibling chunk deduplication (Jaccard on content)
  - tokenizer_version / scoring_version in metadata

Layout (per workspace):
  {ws_root}/{workspace_id}/sys/knowledge/
      sources.jsonl            (v1.0 source store)
      chunks.jsonl             (v1.0.1 chunks: parents + children)
      index.meta.json          (last_build_at, chunk_count, scope_count)
"""

from __future__ import annotations

import json
import math
import os
import re
import threading
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from agent.modules.knowledge.schemas import (
    KnowledgeChunk, KnowledgeSource, SCOPE_PRIORITY,
)


# ── Tunable BM25 params (env-overridable) ──

def _get_bm25_k1() -> float:
    try:
        return float(os.environ.get("KNOWLEDGE_BM25_K1", "1.2"))
    except (TypeError, ValueError):
        return 1.2


def _get_bm25_b() -> float:
    try:
        return float(os.environ.get("KNOWLEDGE_BM25_B", "0.75"))
    except (TypeError, ValueError):
        return 0.75


def _ws_root() -> Path:
    try:
        import workspace.manager as wm
        return wm.WS_ROOT
    except Exception:
        from artifacts.store import _get_ws_root
        return _get_ws_root()


def _index_meta_path(workspace_id: str) -> Path:
    return _ws_root() / workspace_id / "sys/knowledge" / "index.meta.json"


def _chunks_path(workspace_id: str) -> Path:
    return _ws_root() / workspace_id / "sys/knowledge" / "chunks.jsonl"


# Scope boost: per-scope multiplicative score bonus.
SCOPE_BOOST = {"session": 1.30, "workspace": 1.10, "global": 1.00}

# Tokenizer version — bump on breaking tokenizer changes.
TOKENIZER_VERSION = "v1_cjk_ngram"

# Default scoring version.
SCORING_VERSION = "v1_bm25_field_weighted"

# Field weights for index-time weighting. title/chapter/section/
# tags count more than body, but not so much that any title match
# drowns out the actual content. v1.0.2 tuned from
# {4.0, 3.0, 2.0, 2.0, 1.0} to {2.0, 1.5, 1.2, 1.2, 1.0} after
# observing that very high title weight caused OSPF book to
# dominate every OSPF query regardless of body content.
DEFAULT_FIELD_WEIGHTS = {
    "title": 2.0,
    "chapter": 1.5,
    "section": 1.2,
    "tags": 1.2,
    "body": 1.0,
}

# Deduplication: Jaccard similarity threshold on content tokens.
DEDUP_JACCARD_THRESHOLD = 0.85

# Minimum final_score (after scope boost) for a hit to be returned.
# Hits below this are considered "noise" (random CJK n-gram matches
# etc.) and dropped. Tunable via env KNOWLEDGE_MIN_FINAL_SCORE.
def _get_min_final_score() -> float:
    try:
        return float(os.environ.get("KNOWLEDGE_MIN_FINAL_SCORE", "0.5"))
    except (TypeError, ValueError):
        return 0.5

_HIT_SNIPPET_MAX = 200

# ── Tokenization ──

# Match: ASCII word chars + CJK (U+4E00..U+9FFF) chars (treating each
# CJK char as its own token when running the word tokenizer).
_WORD_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", re.UNICODE)
# Match: pure CJK runs of length >= 1 (used for n-gram generation).
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]+", re.UNICODE)


def _is_cjk_char(ch: str) -> bool:
    return "\u4e00" <= ch <= "\u9fff"


def _tokenize_words(s: str) -> List[str]:
    """Word-level tokenization (ASCII words; CJK handled by n-grams).

    v1.0.2: this function used to emit single-char CJK tokens. That
    caused too much noise: a single common CJK char like "的"
    appearing in both query and body counts as a "match", even
    when there is no semantic relevance. The mixed-mode tokenizer
    (`_tokenize_mixed`) handles CJK via 2-gram + 3-gram, so we
    don't need 1-char CJK in word mode.

    ASCII words are still emitted (so "OSPF" remains a single token).
    """
    out: List[str] = []
    for t in _WORD_RE.findall(str(s or "")):
        if _is_cjk_char(t):
            # Skip single CJK chars (n-gram tokenizer handles them).
            continue
        out.append(t.lower())
    return out


def _cjk_ngrams(s: str, ns: Tuple[int, ...] = (2, 3)) -> List[str]:
    """Generate CJK n-grams (2-gram, 3-gram, ...).

    For each contiguous CJK run of length >= min(ns), emit
    sliding-window n-grams of all sizes in `ns`. This captures
    Chinese word boundaries without an external dictionary.
    """
    out: List[str] = []
    for run in _CJK_RUN_RE.findall(str(s or "")):
        for n in ns:
            if len(run) < n:
                continue
            for i in range(0, len(run) - n + 1):
                out.append(run[i:i + n])
    return out


def _tokenize_mixed(s: str, ns: Tuple[int, ...] = (2, 3)) -> List[str]:
    """Mixed-mode tokenization: word tokens + CJK n-grams.

    This is the v1.0.2 default. ASCII words become single tokens;
    CJK runs become both 2-gram and 3-gram tokens. The CJK
    n-grams let us match Chinese substrings without a dictionary
    (e.g. "开放式最短路径优先" → ["开放式", "放式最", "式最短", ...]).
    """
    return _tokenize_words(s) + _cjk_ngrams(s, ns)


# ── Query expansion (deterministic, no LLM) ──

# A static, network-domain abbreviation dictionary. Keys and values
# are matched case-insensitively; values are appended to the user's
# query tokens. We NEVER fabricate chapter / page / score — the
# expansions are only used as additional query terms, never as
# evidence.

QUERY_EXPANSIONS: dict = {
    # Routing protocols
    "ospf": ["开放式最短路径优先", "open shortest path first"],
    "开放式最短路径优先": ["ospf"],
    "bgp": ["边界网关协议", "border gateway protocol"],
    "边界网关协议": ["bgp"],
    "rip": ["路由信息协议", "routing information protocol"],
    "路由信息协议": ["rip"],
    "isis": ["中间系统到中间系统", "intermediate system to intermediate system"],
    "eigrp": ["enhanced interior gateway routing protocol"],
    # OSPF concepts
    "dr": ["designated router", "指定路由器"],
    "bdr": ["backup designated router", "备份指定路由器"],
    "指定路由器": ["dr"],
    "备份指定路由器": ["bdr"],
    "邻居": ["neighbor", "neighbour", "邻接"],
    "邻接": ["neighbor", "neighbour", "邻居"],
    "neighbor": ["邻居", "邻接"],
    "lsa": ["link state advertisement", "链路状态通告"],
    "lsu": ["link state update", "链路状态更新"],
    "链路状态通告": ["lsa"],
    "area": ["区域"],
    "区域": ["area"],
    "asbr": ["autonomous system boundary router", "自治系统边界路由器"],
    "abr": ["area border router", "区域边界路由器"],
    # BGP concepts
    "ibgp": ["internal bgp", "内部边界网关协议"],
    "ebgp": ["external bgp", "外部边界网关协议"],
    "peer": ["对等体", "对端"],
    "对等体": ["peer"],
    "prefix": ["前缀", "网段"],
    "前缀": ["prefix", "网段"],
    "policy": ["策略", "路由策略"],
    "路由策略": ["policy", "route policy"],
    "route-map": ["路由映射", "路由策略"],
    "community": ["团体", "社群属性"],
    # Network general
    "vlan": ["虚拟局域网", "virtual lan"],
    "虚拟局域网": ["vlan"],
    "stp": ["spanning tree protocol", "生成树协议"],
    "生成树协议": ["stp"],
    "acl": ["access control list", "访问控制列表"],
    "访问控制列表": ["acl"],
    "nat": ["network address translation", "网络地址转换"],
    "网络地址转换": ["nat"],
    "qos": ["quality of service", "服务质量"],
    "服务质量": ["qos"],
    "mtu": ["maximum transmission unit", "最大传输单元"],
    "ttl": ["time to live", "生存时间"],
    "tcp": ["transmission control protocol", "传输控制协议"],
    "udp": ["user datagram protocol", "用户数据报协议"],
    "ip": ["internet protocol", "互联网协议"],
    # BFD / HA
    "bfd": ["bidirectional forwarding detection", "双向转发检测"],
    "vrrp": ["virtual router redundancy protocol", "虚拟路由器冗余协议"],
    "虚拟路由器冗余协议": ["vrrp"],
}


def _expand_query(query: str) -> Tuple[str, List[dict]]:
    """Apply deterministic query expansion.

    Returns (expanded_query, expansions_meta) where expansions_meta
    is a list of {term, added} records for the caller to surface in
    metadata.query_expansions.
    """
    query = str(query or "").strip()
    if not query:
        return "", []
    expansions: List[dict] = []
    extras: List[str] = []
    # Match whole-word English abbreviations and CJK substrings.
    # We iterate known keys and check membership; this is O(|dict|)
    # but the dict is small (~60 entries) so it's fine.
    lower_q = query.lower()
    for k, v in QUERY_EXPANSIONS.items():
        k_lower = k.lower()
        # Word boundary for ASCII abbreviations
        if _is_cjk_char(k[0]) if k else False:
            # CJK key — substring match (no word boundary)
            if k in query:
                for x in v:
                    extras.append(x)
                expansions.append({"term": k, "added": list(v)})
        else:
            # ASCII key — word-boundary match
            if re.search(r"(?<![A-Za-z0-9_])" + re.escape(k_lower)
                          + r"(?![A-Za-z0-9_])", lower_q):
                for x in v:
                    extras.append(x)
                expansions.append({"term": k, "added": list(v)})
    if not extras:
        return query, []
    # Dedupe while preserving order
    seen = set()
    deduped = []
    for x in extras:
        x_lower = x.lower()
        if x_lower in seen:
            continue
        seen.add(x_lower)
        deduped.append(x)
    return (query + " " + " ".join(deduped), expansions)


# ── BM25 core ──

class BM25Index:
    """Pure-Python BM25 over a list of pre-tokenized documents.

    Supports field-weighted indexing: a chunk's text is split into
    title / chapter / section / tags / body, each tokenized with the
    mixed-mode tokenizer, and the per-field term counts are
    multiplied by their respective field weights before being summed.

    This means "OSPF" appearing in the title counts 4x more than the
    same term in the body — without sacrificing BM25's length
    normalization properties (since the per-field contributions are
    summed into the same document length).
    """

    def __init__(self, k1: Optional[float] = None, b: Optional[float] = None,
                 field_weights: Optional[dict] = None,
                 cjk_ngram_ns: Tuple[int, ...] = (2, 3)):
        self.k1 = k1 if k1 is not None else _get_bm25_k1()
        self.b = b if b is not None else _get_bm25_b()
        self.field_weights = dict(field_weights or DEFAULT_FIELD_WEIGHTS)
        self.cjk_ngram_ns = tuple(cjk_ngram_ns)
        self.docs: List[KnowledgeChunk] = []
        self.doc_tokens: List[List[str]] = []
        self.doc_lens: List[int] = []
        self.df: Counter = Counter()
        self.avg_dl: float = 0.0
        self.N: int = 0

    def _chunk_fields(self, c: KnowledgeChunk) -> List[Tuple[str, str]]:
        """Decompose a chunk into (field_name, text) pairs.

        title / chapter / section / tags come from chunk metadata +
        fields. body is the raw content.
        """
        meta = c.metadata or {}
        title = meta.get("source_title", "") or c.chapter
        chapter = c.chapter or ""
        section = c.section or ""
        subsection = c.subsection or ""
        tags = " ".join(meta.get("tags") or [])
        body = c.content or ""
        return [
            ("title", title),
            ("chapter", chapter + (" " + subsection if subsection else "")),
            ("section", section),
            ("tags", tags),
            ("body", body),
        ]

    def _tokenize_weighted(self, text: str) -> List[str]:
        """Tokenize a field, repeating tokens by the field weight.

        For weight=4.0 we emit the field's tokens 4 times; for
        weight=0.5 we emit half the tokens. We round down for
        fractional weights (deterministic) and ensure at least 1
        token if the field has any text.
        """
        if not text:
            return []
        toks = _tokenize_mixed(text, self.cjk_ngram_ns)
        if not toks:
            return []
        # Use the field's weight directly via repetition. For
        # fractional weights, we round to nearest int with a floor
        # of 1 to keep things deterministic.
        w = self.field_weights.get(self._cur_field, 1.0)
        if w <= 0:
            return []
        n_repeat = max(1, int(round(w)))
        return toks * n_repeat

    def fit(self, docs: List[KnowledgeChunk]) -> "BM25Index":
        self.docs = list(docs)
        self.doc_tokens = []
        for c in self.docs:
            toks = []
            for fname, ftext in self._chunk_fields(c):
                self._cur_field = fname
                toks.extend(self._tokenize_weighted(ftext))
            self.doc_tokens.append(toks)
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
          - lexical_score: raw BM25
          - semantic_score: null (v1.0.1 reserved; not enabled)
          - final_score: lexical * scope_boost
          - scope: chunk's scope
        """
        if self.N == 0 or not query.strip():
            return []
        q_tokens = _tokenize_mixed(query, self.cjk_ngram_ns)
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
                norm = 1 - self.b + self.b * (dl / max(self.avg_dl, 1e-6))
                scores[i] += idf * (tf * (self.k1 + 1)) / (tf + self.k1 * norm)
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


def _snippet_from_text(text: str, query: str) -> str:
    text = str(text or "")
    if not text:
        return ""
    if not query.strip():
        return text[:_HIT_SNIPPET_MAX]
    q_tokens = _tokenize_words(query)
    lower = text.lower()
    for tok in q_tokens:
        if len(tok) < 2:
            continue
        idx = lower.find(tok.lower())
        if idx >= 0:
            start = max(0, idx - 60)
            end = min(len(text), start + _HIT_SNIPPET_MAX)
            return text[start:end]
    return text[:_HIT_SNIPPET_MAX]


# ── Sibling chunk deduplication ──

def _jaccard(a: List[str], b: List[str]) -> float:
    """Jaccard similarity over token lists."""
    if not a or not b:
        return 0.0
    sa, sb = set(a), set(b)
    inter = sa & sb
    union = sa | sb
    return len(inter) / len(union) if union else 0.0


def _dedupe_sibling_chunks(
    hits: List[dict],
    jaccard_threshold: float = DEDUP_JACCARD_THRESHOLD,
) -> Tuple[List[dict], int]:
    """Post-process search hits: drop near-duplicate siblings.

    Rules (per spec § v1.0.2 三):
      - Same source_id
      - Content (Jaccard) similarity >= threshold
      - Keep only the highest-scored hit per duplicate group
    Cross-source or cross-chapter hits are NEVER deduped (they
    represent independent evidence).

    Returns (deduped_hits, deduplicated_count).
    """
    if len(hits) <= 1:
        return list(hits), 0
    # Tokenize content once for efficiency.
    tokenized = []
    for h in hits:
        c = h.get("_raw_content") or h.get("content") or h.get("snippet") or ""
        tokenized.append(_tokenize_mixed(c))
    kept: List[dict] = []
    kept_tokens: List[List[str]] = []
    dropped = 0
    for i, h in enumerate(hits):
        toks = tokenized[i]
        duplicate_of = None
        for j, kt in enumerate(kept_tokens):
            if (h.get("source_id") != kept[j].get("source_id")):
                # Different source -> never dedupe (independent
                # evidence from different books / docs).
                continue
            # Same source: check Jaccard + chunk adjacency (parent_id)
            if _jaccard(toks, kt) >= jaccard_threshold:
                duplicate_of = j
                break
            # Adjacent siblings (same parent) with high overlap
            if (h.get("parent_chunk_id")
                and h["parent_chunk_id"] == kept[j].get("parent_chunk_id")):
                # The child overlap threshold is also Jaccard but
                # children naturally have high overlap (the
                # OVERLAP parameter in chunking); only dedupe if
                # very high.
                if _jaccard(toks, kt) >= 0.95:
                    duplicate_of = j
                    break
        if duplicate_of is not None:
            dropped += 1
        else:
            kept.append(h)
            kept_tokens.append(toks)
    return kept, dropped


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
    """Return lightweight public view of chunks (safe_excerpt only, no full content).

    safe_excerpt is the first ~200 chars of content, suitable for list display
    without exposing full document text (which is available via read_chunk).
    """
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
            # Lightweight preview: first 200 chars of actual content
            "safe_excerpt": (c.content or "")[:200],
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

    v1.0.2 pipeline:
      1. expand query (deterministic, network-domain dictionary)
      2. enabled-only / scope / source_id / source_type / chapter / tags filters
      3. field-weighted BM25 lexical scoring (title/chapter/section/tags > body)
      4. CJK 2-gram + 3-gram tokenization (mixed-mode)
      5. scope boost
      6. sibling dedup (Jaccard on content)
      7. parent expansion (handled by service layer)

    Returns:
      {
        ok, summary, query, hits (children only, deduped),
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

    # 1. Query expansion (deterministic, no LLM).
    expanded_query, expansions = _expand_query(query)
    # Body filter is checked against the ORIGINAL query tokens (not the
    # expansion), so generic 2-gram substrings from the expansion
    # cannot leak through and let unrelated chunks pass the body
    # filter. The expansion still feeds the BM25 scoring, so recall
    # is preserved.

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
            "metadata": _scoring_meta(workspace_id, "no_candidates",
                                       expansions),
        }
    # Pull 3*top_k first; dedup may collapse some, and we want at
    # least top_k after dedup.
    pull_k = max(top_k * 3, top_k)
    idx = BM25Index().fit(children)
    ranked = idx.score(expanded_query)[:pull_k]

    # Build raw hit dicts (with content for dedup).
    raw_hits = []
    for doc_idx, lex, meta in ranked:
        c = children[doc_idx]
        raw_hits.append({
            "chunk_id": c.chunk_id,
            "source_id": c.source_id,
            "parent_chunk_id": c.parent_chunk_id,
            "title": (c.metadata or {}).get("source_title", ""),
            "chapter": c.chapter,
            "section": c.section,
            "subsection": c.subsection,
            "page_start": c.page_start,
            "page_end": c.page_end,
            "snippet": _snippet_from_text(c.content, expanded_query),
            "score": meta["final_score"],
            "lexical_score": meta["lexical_score"],
            "semantic_score": meta["semantic_score"],
            "scope": meta["scope"],
            "metadata": {
                "chunk_type": c.chunk_type,
                "source_type": (c.metadata or {}).get("source_type", ""),
                "hidden": bool((c.metadata or {}).get("hidden", False)),
                "origin": (c.metadata or {}).get("origin", ""),
                "memory_id": (c.metadata or {}).get("memory_id", ""),
            },
            "_raw_content": c.content,  # used by dedup; not exported
        })

    # Sibling dedup
    deduped, dedup_count = _dedupe_sibling_chunks(raw_hits)
    # Drop hits below the minimum final_score threshold (noise).
    min_score = _get_min_final_score()
    pre_min_filter = len(deduped)
    deduped = [h for h in deduped if (h.get("score") or 0.0) >= min_score]
    min_filtered = pre_min_filter - len(deduped)
    # Require at least 1 ORIGINAL query term to match in the body.
    # Title-only matches (e.g. "完全" appearing in the title
    # "OSPF 完全手册") are filtered out as noise. The body filter
    # is computed against the user's original query (not the
    # expansion), so generic 2-gram substrings from the expansion
    # cannot leak through.
    body_token_sets = {h["chunk_id"]: set(_tokenize_mixed(h.get("_raw_content") or ""))
                       for h in deduped}
    q_token_set = set(_tokenize_mixed(query))
    pre_body_filter = len(deduped)
    body_filtered_deduped = []
    for h in deduped:
        body_set = body_token_sets.get(h["chunk_id"], set())
        if body_set & q_token_set:
            body_filtered_deduped.append(h)
    body_filtered = pre_body_filter - len(body_filtered_deduped)
    final_hits = body_filtered_deduped[:top_k]

    hits = []
    for h in final_hits:
        h = {k: v for k, v in h.items() if k != "_raw_content"}
        hits.append(h)

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
        "metadata": _scoring_meta(workspace_id, "bm25_v1_field_weighted",
                                   expansions, dedup_count,
                                   pre_dedup_count=len(raw_hits),
                                   min_score_threshold=min_score,
                                   min_filtered=min_filtered,
                                   body_filtered=body_filtered),
    }


def _scoring_meta(workspace_id: str, scoring: str,
                    expansions: Optional[list] = None,
                    deduplicated_count: int = 0,
                    pre_dedup_count: int = 0,
                    min_score_threshold: float = 0.0,
                    min_filtered: int = 0,
                    body_filtered: int = 0) -> dict:
    return {
        "retrieval_backend": "local_bm25",
        "scoring": scoring,
        "scoring_version": SCORING_VERSION,
        "tokenizer_version": TOKENIZER_VERSION,
        "lexical_score_present": True,
        "semantic_score_present": False,
        "semantic_status": "not_enabled",
        "scope_priority": list(SCOPE_PRIORITY.keys()),
        "workspace_id": workspace_id,
        "query_expansions": list(expansions or []),
        "deduplicated_count": int(deduplicated_count),
        "pre_dedup_count": int(pre_dedup_count),
        "min_score_threshold": float(min_score_threshold),
        "min_filtered": int(min_filtered),
        "body_filtered": int(body_filtered),
    }
