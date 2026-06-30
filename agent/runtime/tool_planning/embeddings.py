# agent/runtime/tool_planning/embeddings.py
"""Lightweight tool-description embedding store.

No external dependencies — uses our CJK tokenizer + BM25 + TF-IDF vector
to build sparse vectors for tool descriptions. Supports cosine similarity
between a query and all indexed tools.

Vectors are cached to disk (JSON) so they survive restarts.
"""

from __future__ import annotations

import json
import math
import time
from collections import defaultdict
from pathlib import Path
from typing import Optional

from agent.runtime.utils import now_iso, from_iso
from context.unified_retriever import tokenize  # CJK unigram+bigram tokenizer


# ── Cache path ────────────────────────────────────────────────────────

def _cache_path() -> Path:
    """Cache file for precomputed tool embeddings."""
    from storage.paths import get_workspace_root
    p = get_workspace_root() / ".tool_embeddings_cache.json"
    return p


CACHE_TTL_SECONDS = 3600  # Recompute embeddings every hour


# ── TF-IDF vector builder ─────────────────────────────────────────────

class ToolEmbeddingStore:
    """Build and query a sparse TF-IDF vector index over tool descriptions."""

    def __init__(self):
        self._tool_ids: list[str] = []
        self._vectors: list[dict[str, float]] = []  # token → weight per tool
        self._idf: dict[str, float] = {}            # token → idf
        self._built_at: str = ""

    # ── Build ──────────────────────────────────────────────────────────

    def build(self, tool_descriptions: list[tuple[str, str]]) -> None:
        """Build vectors from (tool_id, description_text) pairs.

        Uses TF-IDF weighting with sublinear tf scaling (1 + log(tf)).
        """
        self._tool_ids = []
        docs: list[dict[str, float]] = []
        df: dict[str, int] = defaultdict(int)

        for tid, text in tool_descriptions:
            tokens = tokenize(text)
            if not tokens:
                continue
            tf: dict[str, int] = defaultdict(int)
            for t in tokens:
                tf[t] += 1
            # Sublinear TF scaling: 1 + log(tf)
            doc_vec = {t: 1.0 + math.log(cnt) for t, cnt in tf.items()}
            docs.append(doc_vec)
            self._tool_ids.append(tid)
            for t in doc_vec:
                df[t] += 1

        n = len(docs)
        self._idf = {t: math.log((n + 1) / (df[t] + 1)) + 1.0 for t in df}
        self._vectors = docs
        self._built_at = now_iso()

    # ── Query ──────────────────────────────────────────────────────────

    def search(self, query: str, top_k: int = 20) -> list[tuple[str, float]]:
        """Return top_k (tool_id, score) ranked by cosine similarity."""
        if not self._vectors:
            return []

        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        # Build query TF vector
        qtf: dict[str, int] = defaultdict(int)
        for t in query_tokens:
            qtf[t] += 1
        qvec = {t: (1.0 + math.log(cnt)) * self._idf.get(t, 0.0)
                for t, cnt in qtf.items() if t in self._idf}
        qnorm = math.sqrt(sum(v * v for v in qvec.values())) or 1.0

        scores: list[tuple[str, float]] = []
        for tid, dvec in zip(self._tool_ids, self._vectors):
            # Cosine similarity (normalized dot product)
            dot = sum(qvec.get(t, 0.0) * dvec.get(t, 0.0) for t in set(qvec) | set(dvec))
            dnorm = math.sqrt(sum(v * v for v in dvec.values())) or 1.0
            sim = dot / (qnorm * dnorm) if (qnorm * dnorm) > 0 else 0.0
            if sim > 0:
                scores.append((tid, sim))
        scores.sort(key=lambda x: -x[1])
        return scores[:top_k]

    # ── Persistence ────────────────────────────────────────────────────

    def save(self) -> None:
        try:
            data = {
                "tool_ids": self._tool_ids,
                "idf": self._idf,
                "vectors": self._vectors,
                "built_at": self._built_at,
                "tool_count": len(self._tool_ids),
            }
            _cache_path().write_text(json.dumps(data, ensure_ascii=False))
        except Exception:
            pass

    def load(self) -> bool:
        """Try loading from cache. Returns True if cache was valid."""
        p = _cache_path()
        if not p.exists():
            return False
        try:
            data = json.loads(p.read_text())
            built_at_raw = data.get("built_at")
            if not isinstance(built_at_raw, str):
                return False
            built_at_epoch = from_iso(built_at_raw)
            age = time.time() - built_at_epoch
            if age > CACHE_TTL_SECONDS:
                return False
            self._tool_ids = data["tool_ids"]
            self._idf = data["idf"]
            self._vectors = data["vectors"]
            self._built_at = built_at_raw
            return True
        except Exception:
            return False

    @property
    def tool_count(self) -> int:
        return len(self._tool_ids)

    @property
    def age_seconds(self) -> float:
        if not self._built_at:
            return float("inf")
        try:
            return time.time() - from_iso(self._built_at)
        except (TypeError, ValueError):
            return float("inf")


# ── Module-level singleton ─────────────────────────────────────────────

_store: Optional[ToolEmbeddingStore] = None


def get_embedding_store() -> ToolEmbeddingStore:
    global _store
    if _store is None:
        _store = ToolEmbeddingStore()
        if not _store.load():
            _build_tool_embeddings(_store)
    elif _store.age_seconds > CACHE_TTL_SECONDS:
        _build_tool_embeddings(_store)
    return _store


def _build_tool_embeddings(store: ToolEmbeddingStore) -> None:
    """Build embeddings from all tools in TOOL_NAMESPACE."""
    from tool_runtime.tool_namespace import TOOL_NAMESPACE

    descriptions: list[tuple[str, str]] = []
    for tid, entry in sorted(TOOL_NAMESPACE.items()):
        # Build a rich description string from all available metadata
        parts = [
            entry.display_name,
            entry.category,
            entry.group,
            entry.action,
            entry.usage_hint or "",
            entry.not_for or "",
        ]
        text = " ".join(p for p in parts if p)
        descriptions.append((tid, text))

    store.build(descriptions)
    store.save()
