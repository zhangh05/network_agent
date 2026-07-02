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

from core.context.context_store import get_context_store


# ---------------------------------------------------------------------------
# Tokenization (shared for indexing and querying)
# ---------------------------------------------------------------------------

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
_WORD_RE = re.compile(r"[a-zA-Z0-9_\-\.]+|[\u4e00-\u9fff\u3400-\u4dbf]")

def tokenize(text: str, cjk_ngram_ns: tuple[int, ...] = (1, 2)) -> list[str]:
    """Tokenize text into terms. CJK uses n-gram with stopword filter; Latin uses word split.

    v3.2: Added unigram to improve short-query recall. Added CJK stopword filter
    to remove semantically meaningless n-grams (particles, punctuation fragments).
    """
    if not text:
        return []
    text = text.lower()
    tokens: list[str] = []

    # Latin words
    for m in _WORD_RE.finditer(text):
        w = m.group()
        if len(w) > 1 or not _CJK_RE.match(w):
            tokens.append(w)

    # CJK n-grams with stopword filter
    cjk_chars = _CJK_RE.findall(text)
    cjk_str = "".join(cjk_chars)
    for n in cjk_ngram_ns:
        for i in range(len(cjk_str) - n + 1):
            token = cjk_str[i:i + n]
            if token not in _CJK_STOPWORDS:
                tokens.append(token)

    return tokens


# CJK stopwords — meaningless n-grams that add noise
_CJK_STOPWORDS: set[str] = {
    # Common function particles (bigrams)
    "的是", "了这", "在那", "的一", "了不", "了个", "是这",
    "之的", "为的", "所这", "和其", "于这", "被那",
    "这个", "那个", "一个", "这种", "那种", "一些", "这些",
    "我们", "他们", "你们", "它一", "自一",
    # Single characters that appear as unigrams (too short/generic)
    "的", "了", "是", "在", "和", "与", "之", "为",
    "所", "以", "这", "那", "一", "不", "也", "有",
    "人", "要", "会", "就", "能", "对", "说", "向",
    "用", "被", "当", "但", "从", "而", "去",
    # Punctuation-near CJK (common noise)
    "由一", "因这", "如此", "因此",
}


# ---------------------------------------------------------------------------
# Network domain query expansion (static dictionary)
# ---------------------------------------------------------------------------

_NET_SYNONYMS: dict[str, list[str]] = {
    # ── IP / address ──
    "ip": ["ip地址", "address", "ipv4", "ipv6"],
    "ip地址": ["ip", "address"],
    "地址": ["address", "ip"],
    "address": ["ip", "地址"],
    # ── 交换机 ──
    "交换机": ["switch", "三层交换", "l2", "l3", "二层", "三层", "交换"],
    "switch": ["交换机", "交换"],
    "交换": ["switch", "交换机"],
    "二层": ["l2", "layer2", "交换机"],
    "三层": ["l3", "layer3", "路由", "交换机"],
    # ── 路由器 ──
    "路由器": ["router", "路由", "gateway", "网关"],
    "router": ["路由器", "路由"],
    "路由": ["router", "route", "路由器", "ospf", "bgp"],
    # ── 防火墙 / 安全 ──
    "防火墙": ["firewall", "security", "安全"],
    "firewall": ["防火墙", "安全"],
    "安全": ["security", "firewall", "防火墙"],
    "acl": ["access-list", "access list", "访问控制", "访问控制列表"],
    "访问控制": ["acl", "access-list"],
    # ── VLAN ──
    "vlan": ["虚拟局域网", "virtual lan"],
    "虚拟局域网": ["vlan"],
    # ── 路由协议 ──
    "bgp": ["边界网关", "border gateway"],
    "边界网关": ["bgp"],
    "ospf": ["开放最短路径", "link state", "链路状态"],
    "开放最短路径": ["ospf"],
    "rip": ["路由信息协议", "distance vector"],
    "static": ["静态", "静态路由"],
    "静态路由": ["static", "static route"],
    # ── 接口 / 端口 ──
    "接口": ["interface", "端口", "port"],
    "interface": ["接口", "端口", "port"],
    "端口": ["port", "interface", "接口"],
    "port": ["端口", "接口"],
    # ── 配置 ──
    "配置": ["config", "configuration", "设置", "configure"],
    "config": ["配置", "configuration"],
    "configuration": ["配置", "config"],
    # ── 常见设备 ──
    "huawei": ["华为"],
    "华为": ["huawei"],
    "cisco": ["思科"],
    "思科": ["cisco"],
    "h3c": ["华三"],
    "华三": ["h3c"],
    # ── 协议 ──
    "ssh": ["secure shell", "安全外壳"],
    "telnet": ["远程登录"],
    "snmp": ["simple network management", "网络管理"],
    "tcp": ["传输控制", "transmission control"],
    "udp": ["用户数据报", "user datagram"],
    # ── 排查 / 运维 ──
    "排查": ["troubleshoot", "debug", "诊断", "排错", "troubleshooting"],
    "诊断": ["diagnose", "排查", "troubleshoot"],
    "监控": ["monitor", "monitoring", "watch", "观察"],
    "备份": ["backup", "save", "保存"],
    "恢复": ["restore", "recovery", "还原"],
    "升级": ["upgrade", "update", "更新"],
    # ── 网络概念 ──
    "nat": ["network address translation", "网络地址转换", "地址转换"],
    "dhcp": ["dynamic host configuration", "动态主机配置"],
    "dns": ["domain name system", "域名解析", "域名"],
    "qos": ["quality of service", "服务质量", "流量控制"],
    "stp": ["spanning tree", "生成树"],
    "生成树": ["stp", "spanning tree"],
    "链路聚合": ["lacp", "link aggregation", "eth-trunk"],
    "eth-trunk": ["链路聚合", "lacp"],
    "隧道": ["tunnel", "gre", "vpn"],
    "vpn": ["虚拟专用网", "隧道", "tunnel"],
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

        # Apply post-score boosts: recency, confirmation, frequency
        results = self._apply_boosts(results)

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
    def _apply_boosts(results: list[dict]) -> list[dict]:
        """Apply post-BM25 boosts: recency, confirmation.

        v3.9.7: Time-weighted scoring ensures recent memories rank higher.
        Confirmed/active memories get a confidence boost.

        Note: frequency boost (access_count) is reserved for future use
        when per-item access tracking is implemented on ContextStore.
        """
        if not results:
            return results

        now = time.time()
        for hit in results:
            boost = 1.0
            score = hit.get("_score", 0.0)

            # ── Recency boost (time decay) ──
            created_at = hit.get("created_at", "")
            if created_at:
                try:
                    age_s = now - _ts_to_epoch(created_at)
                    if age_s <= 0 or age_s > 31536000:   # invalid or >1yr old
                        pass
                    elif age_s < 300:                     # < 5 min
                        boost *= 2.0
                    elif age_s < 3600:                    # < 1 hour
                        boost *= 1.5
                    elif age_s < 86400:                   # < 1 day
                        boost *= 1.2
                    elif age_s < 604800:                  # < 1 week
                        boost *= 1.05
                except Exception:
                    pass

            # ── Confirmation boost ──
            status = str(hit.get("status", "")).lower()
            if status in ("active", "confirmed"):
                boost *= 1.3

            hit["_boost"] = round(boost, 3)
            hit["_score"] = round(score * boost, 4)

        # Re-sort by boosted score
        results.sort(key=lambda h: -h["_score"])
        return results

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
# Helpers
# ---------------------------------------------------------------------------

def _ts_to_epoch(ts: str) -> float:
    """Parse ISO 8601 timestamp to epoch seconds. Returns 0 on failure."""
    import datetime
    try:
        ts = ts.replace("Z", "+00:00")
        return datetime.datetime.fromisoformat(ts).timestamp()
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Singleton helper
# ---------------------------------------------------------------------------
_retrievers: dict[str, UnifiedRetriever] = {}

def get_retriever(workspace_id: str = "default") -> UnifiedRetriever:
    """Return the singleton UnifiedRetriever for a workspace."""
    if workspace_id not in _retrievers:
        _retrievers[workspace_id] = UnifiedRetriever(workspace_id)
    return _retrievers[workspace_id]
