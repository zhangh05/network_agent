# agent/runtime/tool_planning/hybrid_retriever.py
"""Hybrid tool retriever: BM25 keyword + embedding vector + RRF fusion.

Combines the existing BM25/CJK keyword matching from CapabilityRouter
with the new TF-IDF embedding store for semantic matching.

Fusion strategy: Reciprocal Rank Fusion (RRF)
  score = alpha * 1/(k + rank_semantic) + (1-alpha) * 1/(k + rank_keyword)

Default: k=60, alpha=0.6 (60% semantic, 40% keyword).
"""

from __future__ import annotations

from typing import Any, Optional

from agent.runtime.tool_planning.embeddings import get_embedding_store

# ── RRF constants ──────────────────────────────────────────────────────

RRF_K = 60        # Smoothing constant (higher = more weight to low-ranked items)
RRF_ALPHA = 0.6   # Semantic weight (0-1). 0.6 = 60% semantic, 40% keyword


# ── Keyword matching ───────────────────────────────────────────────────

def _keyword_score(tool_id: str, user_input: str, capability_router=None) -> float:
    """Score a tool by keyword match using the existing CapabilityRouter patterns.

    If capability_router is provided, use its internal keyword database.
    Otherwise, fall back to simple substring matching on namespace metadata.
    """
    lower_input = user_input.lower()

    # Try capability router's keyword matching first
    if capability_router is not None:
        try:
            route = capability_router.route_keywords(user_input)
            for pkg in route.packages:
                for tid in pkg.tool_ids:
                    if tid == tool_id:
                        # Use the package's match score
                        return route.confidence.get(tid, 0.5)
        except Exception:
            pass

    # Fallback: simple substring matching against namespace metadata
    from tool_runtime.tool_namespace import TOOL_NAMESPACE
    entry = TOOL_NAMESPACE.get(tool_id)
    if entry is None:
        return 0.0

    search_text = f"{entry.display_name} {entry.usage_hint or ''}".lower()
    score = 0.0

    # Full match on common patterns
    for word in lower_input.split():
        if word in search_text:
            score += 0.2
    if lower_input in search_text:
        score += 0.5

    return min(score, 1.0)


# ── Hybrid search ──────────────────────────────────────────────────────

def hybrid_tool_search(
    user_input: str,
    top_k: int = 30,
    capability_router=None,
    scene: Any = None,
) -> list[tuple[str, float]]:
    """Search for relevant tools using hybrid keyword + semantic retrieval.

    Returns a ranked list of (tool_id, rrf_score) tuples.
    """
    # 1. Semantic retrieval
    store = get_embedding_store()
    semantic_results = store.search(user_input, top_k=top_k)

    # 2. Build rank maps
    semantic_rank: dict[str, int] = {}
    for rank, (tid, score) in enumerate(semantic_results, 1):
        semantic_rank[tid] = rank

    # 3. Keyword matching — score ALL tools via keyword
    keyword_scores: dict[str, float] = {}
    from tool_runtime.tool_namespace import TOOL_NAMESPACE
    from tool_runtime.tool_governance import is_planner_visible

    for tid in TOOL_NAMESPACE:
        if not is_planner_visible(tid):
            continue
        ks = _keyword_score(tid, user_input, capability_router)
        if ks > 0:
            keyword_scores[tid] = ks

    # Sort keyword results by score descending to assign ranks
    keyword_ranked = sorted(keyword_scores.items(), key=lambda x: -x[1])
    keyword_rank: dict[str, int] = {}
    for rank, (tid, _) in enumerate(keyword_ranked, 1):
        keyword_rank[tid] = rank

    # 4. RRF fusion
    all_tool_ids = set(semantic_rank) | set(keyword_rank)
    fused: list[tuple[str, float]] = []
    for tid in all_tool_ids:
        sr = semantic_rank.get(tid, top_k + 1)
        kr = keyword_rank.get(tid, top_k + 1)
        rrf = (RRF_ALPHA / (RRF_K + sr)) + ((1 - RRF_ALPHA) / (RRF_K + kr))
        fused.append((tid, round(rrf, 6)))
    fused.sort(key=lambda x: -x[1])

    # 5. Cap result to top_k
    result = fused[:top_k]

    return result


# ── Capability-aware hybrid search ─────────────────────────────────────

def capability_hybrid_search(
    user_input: str,
    scene: Any = None,
    safe_context: dict | None = None,
    limit: int = 10,
    recently_used_tools: list[str] | None = None,
) -> list[tuple[str, float]]:
    """Search that respects capability routing context + graph boost.

    First runs hybrid_tool_search, then filters by capability route
    if scene context is available (boosts tools from matched capabilities).
    Finally applies graph co-occurrence boost for tools related to recently-used tools.
    """
    from agent.runtime.capability_routing.router import route_capabilities

    results = hybrid_tool_search(user_input, top_k=50)

    # If scene is available, boost capability-matched tools
    if scene is not None:
        try:
            route = route_capabilities(user_input, scene=scene, safe_context=safe_context, limit=3)
            capability_tool_ids = set()
            for pkg in route.packages:
                capability_tool_ids.update(pkg.tool_ids)

            for i, (tid, score) in enumerate(results):
                if tid in capability_tool_ids:
                    results[i] = (tid, min(score * 1.5, 1.0))
            results.sort(key=lambda x: -x[1])
        except Exception:
            pass

    # Apply graph co-occurrence boost
    if recently_used_tools:
        try:
            from agent.runtime.tool_planning.graph import boost_scores_with_graph
            results = boost_scores_with_graph(results, recently_used_tools)
        except Exception:
            pass

    return results[:limit]
