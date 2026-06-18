# context/unified_retriever.py
"""UnifiedRetriever — single BM25 engine for memory + knowledge retrieval.

Replaces:
  - memory/retriever.py  (BM25 on JSONL + backfill hack)
  - agent/modules/knowledge/index.py search_chunks()

All retrievable items live in ContextStore and share the same BM25
scoring pipeline.  Callers filter by ``item_type`` to get memory-only
or knowledge-only results.

Features:
  - Field-weighted BM25 (title > section/chapter > content)
  - CJK bigram/trigram tokenization
  - Scope boosting (session > workspace > global)
  - Jaccard sibling dedup
  - Query expansion via static network-term dictionary
  - Unified result schema

v3.1.0: Created as part of P1-P5 refactoring.
"""

from __future__ import annotations

import math
import re
import os
import time
import threading
from collections import Counter, defaultdict
from typing import Optional
from pathlib import Path

from context.context_store import get_context_store


# ---------------------------------------------------------------------------
# Tokenization (shared for indexing and querying)
# ---------------------------------------------------------------------------

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
_WORD_RE = re.compile(r"[a-zA-Z0-9_\-\.]+|[\u4e00-\u9fff\u3400-\u4dbf]")

def tokenize(text: str, cjk_ngram_ns: tuple[int, ...] = (2, 3)) -> list[str]:
    """Tokenize text into terms. CJK uses n-gram; Latin uses word split."""
    if not text:
        return []
    text = text.lower()
    tokens: list[str] = []

    # Latin words
    for m in _WORD_RE.finditer(text):
        w = m.group()
        if len(w) > 1 or not _CJK_RE.match(w):
            tokens.append(w)

    # CJK n-grams
    cjk_chars = _CJK_RE.findall(text)
    cjk_str = "".join(cjk_chars)
    for n in cjk_ngram_ns:
        for i in range(len(cjk_str) - n + 1):
            tokens.append(cjk_str[i:i + n])

    return tokens


# ---------------------------------------------------------------------------
# Network domain query expansion (static dictionary)
# ---------------------------------------------------------------------------

_NET_SYNONYMS: dict[str, list[str]] = {
    "ip": ["ip地址", "地址", "address", "ipv4", "ipv6"],
    "ip地址": ["ip", "address"],
    "交换机": ["switch", "三层交换"],
    "switch": ["交换机"],
    "路由器": ["router", "路由"],
    "router": ["路由器"],
    "防火墙": ["firewall"],
    "firewall": ["防火墙"],
    "vlan": ["虚拟局域网"],
    "bgp": ["边界网关"],
    "ospf": ["开放最短路径"],
    "接口": ["interface", "端口", "port"],
    "interface": ["接口", "端口"],
    "配置": ["config", "configuration", "设置"],
    "config": ["配置", "configuration"],
}

def expand_query(query: str) -> str:
    """Add domain-specific synonyms to the query."""
    terms = tokenize(query)
    expanded = set(terms)
    for t in terms:
        if t in _NET_SYNONYMS:
            expanded.update(_NET_SYNONYMS[t])
    # Return original query + expansions
    return query + " " + " ".join(expanded - set(terms))


# ---------------------------------------------------------------------------
# Scope boost factors
# ---------------------------------------------------------------------------

_SCOPE_BOOST = {
    "session": 1.5,
    "workspace": 1.2,
    "global": 1.0,
}

# ---------------------------------------------------------------------------
# Field weights
# ---------------------------------------------------------------------------

_FIELD_WEIGHTS = {
    "title": 3.0,
    "chapter": 2.0,
    "section": 2.0,
    "tags": 2.5,
    "summary": 1.5,
    "index_text": 1.2,
    "content": 1.0,
}


# ---------------------------------------------------------------------------
# BM25 Engine
# ---------------------------------------------------------------------------

class _BM25:
    """Minimal BM25 implementation over a list of doc dicts."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.docs: list[dict] = []
        self.doc_lens: list[int] = []
        self.avgdl: float = 0
        self.df: dict[str, int] = defaultdict(int)     # term -> doc frequency
        self.tf: list[dict[str, float]] = []            # per-doc term -> weighted freq
        self.n: int = 0
        self._built = False

    def fit(self, docs: list[dict]):
        """Build index from doc dicts."""
        self.docs = docs
        self.n = len(docs)
        self.doc_lens = []
        self.tf = []
        self.df = defaultdict(int)

        for doc in docs:
            tf_counter: Counter = Counter()
            total_len = 0
            for field, weight in _FIELD_WEIGHTS.items():
                text = doc.get(field, "")
                if isinstance(text, list):
                    text = " ".join(str(t) for t in text)
                elif not isinstance(text, str):
                    text = str(text) if text else ""
                terms = tokenize(text)
                total_len += len(terms)
                for t in terms:
                    tf_counter[t] += weight

            self.doc_lens.append(total_len)
            self.tf.append(dict(tf_counter))

            for t in set(tf_counter.keys()):
                self.df[t] += 1

        self.avgdl = sum(self.doc_lens) / max(self.n, 1)
        self._built = True

    def score(self, query: str, top_k: int = 10) -> list[tuple[int, float]]:
        """Return [(doc_index, score)] sorted descending."""
        if not self._built or self.n == 0:
            return []

        q_terms = tokenize(query)
        if not q_terms:
            return []

        scores: list[float] = [0.0] * self.n
        for qt in q_terms:
            if qt not in self.df:
                continue
            idf = math.log((self.n - self.df[qt] + 0.5) / (self.df[qt] + 0.5) + 1.0)
            for i in range(self.n):
                tf_val = self.tf[i].get(qt, 0.0)
                if tf_val == 0:
                    continue
                dl = self.doc_lens[i]
                tf_norm = (tf_val * (self.k1 + 1)) / (
                    tf_val + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
                )
                scores[i] += idf * tf_norm

        # Apply scope boost
        for i, doc in enumerate(self.docs):
            scope = doc.get("scope", "global")
            scores[i] *= _SCOPE_BOOST.get(scope, 1.0)

        # Rank
        ranked = [(i, s) for i, s in enumerate(scores) if s > 0]
        ranked.sort(key=lambda x: x[1], reverse=True)
        return ranked[:top_k]


# ---------------------------------------------------------------------------
# UnifiedRetriever
# ---------------------------------------------------------------------------

class UnifiedRetriever:
    """Single retriever for all item types in a workspace."""

    def __init__(self, workspace_id: str = "default"):
        self.workspace_id = workspace_id
        self._store = get_context_store(workspace_id)
        self._bm25 = _BM25()
        self._indexed_count = 0
        self._last_index_time = 0.0
        self._lock = threading.RLock()

    def _maybe_reindex(self):
        """Rebuild BM25 index if store has changed."""
        items = self._store.all_items()
        count = len(items)
        if count != self._indexed_count or (
            time.time() - self._last_index_time > 30
        ) or (count > 0 and not self._bm25._built):
            with self._lock:
                # Re-read in case of concurrent update
                items = self._store.all_items()
                self._bm25.fit(items)
                self._indexed_count = len(items)
                self._last_index_time = time.time()

    def search(
        self,
        query: str,
        item_type: Optional[str] = None,
        item_types: Optional[list[str]] = None,
        scope: Optional[str] = None,
        source_id: Optional[str] = None,
        tags: Optional[list[str]] = None,
        top_k: int = 10,
        min_score: float = 0.1,
        expand: bool = True,
    ) -> list[dict]:
        """Search for items matching *query*.

        Args:
            query:      Natural language query.
            item_type:  Filter to a single type (e.g. "memory_hit").
            item_types: Filter to multiple types.
            scope:      Filter by scope.
            source_id:  Filter by source_id.
            tags:       Filter by tags (any-match).
            top_k:      Max results.
            min_score:  Minimum BM25 score threshold.
            expand:     Whether to apply query expansion.

        Returns:
            List of item dicts, each with an added ``_score`` field.
        """
        self._maybe_reindex()

        effective_query = expand_query(query) if expand else query
        raw_results = self._bm25.score(effective_query, top_k=top_k * 3)

        # Post-filter
        results: list[dict] = []
        types_filter = set()
        if item_type:
            types_filter.add(item_type)
        if item_types:
            types_filter.update(item_types)

        for idx, score in raw_results:
            if score < min_score:
                continue
            doc = self._bm25.docs[idx]

            # Type filter
            if types_filter and doc.get("item_type") not in types_filter:
                continue
            # Scope filter
            if scope and doc.get("scope") != scope:
                continue
            # Source filter
            if source_id and doc.get("source_id") != source_id:
                continue
            # Tags filter
            if tags:
                doc_tags = set(doc.get("tags") or [])
                if not doc_tags.intersection(tags):
                    continue

            hit = dict(doc)
            hit["_score"] = round(score, 4)
            results.append(hit)

            if len(results) >= top_k:
                break

        # Dedup by content similarity (Jaccard on tokens)
        results = self._dedup_results(results)

        return results

    def search_memory(self, query: str, top_k: int = 5, **kwargs) -> list[dict]:
        """Convenience: search memory_hit items only."""
        return self.search(query, item_type="memory_hit", top_k=top_k, **kwargs)

    def search_knowledge(self, query: str, top_k: int = 5, **kwargs) -> list[dict]:
        """Convenience: search knowledge_chunk items only."""
        return self.search(query, item_type="knowledge_chunk", top_k=top_k, **kwargs)

    def retrieve_for_context(
        self,
        query: str,
        top_k_memory: int = 5,
        top_k_knowledge: int = 5,
    ) -> dict:
        """Retrieve both memory and knowledge hits for context building.

        Returns:
            {"memory_hits": [...], "knowledge_hits": [...]}
        """
        memory = self.search_memory(query, top_k=top_k_memory)
        knowledge = self.search_knowledge(query, top_k=top_k_knowledge)
        return {
            "memory_hits": memory,
            "knowledge_hits": knowledge,
        }

    @staticmethod
    def _dedup_results(results: list[dict], threshold: float = 0.75) -> list[dict]:
        """Remove near-duplicate results by Jaccard similarity on content tokens."""
        if len(results) <= 1:
            return results

        kept: list[dict] = []
        kept_tokens: list[set[str]] = []

        for r in results:
            content = r.get("content", "")
            if isinstance(content, dict):
                content = str(content)
            toks = set(tokenize(content))
            if not toks:
                kept.append(r)
                kept_tokens.append(toks)
                continue

            is_dup = False
            for kt in kept_tokens:
                if not kt:
                    continue
                jaccard = len(toks & kt) / len(toks | kt)
                if jaccard > threshold:
                    is_dup = True
                    break

            if not is_dup:
                kept.append(r)
                kept_tokens.append(toks)

        return kept


# ---------------------------------------------------------------------------
# Singleton helper
# ---------------------------------------------------------------------------
_retrievers: dict[str, UnifiedRetriever] = {}

def get_retriever(workspace_id: str = "default") -> UnifiedRetriever:
    """Return the singleton UnifiedRetriever for a workspace."""
    if workspace_id not in _retrievers:
        _retrievers[workspace_id] = UnifiedRetriever(workspace_id)
    return _retrievers[workspace_id]
