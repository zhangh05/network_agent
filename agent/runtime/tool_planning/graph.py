# agent/runtime/tool_planning/graph.py
"""Lightweight tool co-occurrence graph.

Tracks which tools are commonly called together in the same turn,
and boosts related tools in subsequent searches.

Design:
  - In-memory graph: tool_id → {related_tool_id: co_occurrence_count}
  - Updated after each turn based on the actual tool calls made
  - Boosts: multiply hybrid search scores by 1.2x for tools that
    frequently co-occur with recently-used tools

Inspired by AutoTool Graph (arXiv:2511.14650):
  "Tool selection has inertia — certain combinations frequently appear
   together. The graph handles 'what comes next', retrieval handles
   'what the query needs'."
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Optional

# ── In-memory graph store ──────────────────────────────────────────────

# Graph structure: tool_id → {related_tool_id: count}
_co_graph: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))


def record_tool_sequence(tool_ids: list[str]) -> None:
    """Record a sequence of tool calls from a completed turn.
    
    Each pair of tools in the sequence gets a co-occurrence count bump.
    """
    if len(tool_ids) < 2:
        return
    
    unique = list(dict.fromkeys(tool_ids))  # deduplicate within same turn
    for i, tid_a in enumerate(unique):
        for tid_b in unique[i + 1:]:
            _co_graph[tid_a][tid_b] += 1
            _co_graph[tid_b][tid_a] += 1


def get_related_tools(tool_id: str, min_count: int = 1, top_k: int = 5) -> list[tuple[str, int]]:
    """Get top related tools for a given tool, sorted by co-occurrence count."""
    related = _co_graph.get(tool_id, {})
    sorted_related = sorted(
        [(t, c) for t, c in related.items() if c >= min_count],
        key=lambda x: -x[1],
    )
    return sorted_related[:top_k]


def boost_scores_with_graph(
    candidate_scores: list[tuple[str, float]],
    recently_used_tools: list[str],
    boost_factor: float = 1.2,
) -> list[tuple[str, float]]:
    """Boost scores for tools that co-occur with recently-used tools.
    
    For each recently-used tool, find its related tools in the graph
    and boost their scores by boost_factor.
    
    Args:
        candidate_scores: (tool_id, score) list from hybrid search
        recently_used_tools: tool IDs used in the last 1-2 turns
        boost_factor: multiplier for scores (default 1.2 for subtle boost)
    
    Returns:
        Re-ranked list of (tool_id, boosted_score)
    """
    if not recently_used_tools:
        return candidate_scores
    
    # Collect all co-occurring tool IDs
    boost_set: dict[str, float] = {}
    for tool_id in recently_used_tools:
        related = _co_graph.get(tool_id, {})
        total = sum(related.values()) or 1
        for rel_tid, count in related.items():
            # More co-occurrence = bigger boost
            weight = 1.0 + (count / total) * (boost_factor - 1.0)
            if rel_tid not in boost_set or weight > boost_set[rel_tid]:
                boost_set[rel_tid] = weight
    
    if not boost_set:
        return candidate_scores
    
    # Apply boosts
    boosted = []
    for tid, score in candidate_scores:
        bf = boost_set.get(tid, 1.0)
        boosted.append((tid, score * bf))
    
    boosted.sort(key=lambda x: -x[1])
    return boosted


def save_graph(path: Optional[str] = None) -> None:
    """Persist the graph to disk as JSON."""
    import json
    from storage.paths import get_workspace_root
    p = path or str(get_workspace_root() / ".tool_graph.json")
    try:
        # Convert defaultdict to regular dict for serialization
        serializable = {
            tid: dict(related) for tid, related in _co_graph.items()
        }
        with open(p, "w") as f:
            json.dump(serializable, f, ensure_ascii=False)
    except Exception:
        pass


def load_graph(path: Optional[str] = None) -> int:
    """Load the graph from disk. Returns number of edges loaded."""
    import json
    from storage.paths import get_workspace_root
    p = path or str(get_workspace_root() / ".tool_graph.json")
    try:
        with open(p) as f:
            data = json.load(f)
        for tid, related in data.items():
            for rel_tid, count in related.items():
                _co_graph[tid][rel_tid] = count
        return sum(len(r) for r in data.values())
    except (FileNotFoundError, json.JSONDecodeError):
        return 0


def graph_stats() -> dict:
    """Return basic statistics about the graph."""
    nodes = len(_co_graph)
    edges = sum(len(r) for r in _co_graph.values())
    return {
        "nodes": nodes,
        "edges": edges,
        "top_pairs": [
            {"from": a, "to": b, "count": c}
            for a, b, c in sorted(
                [(a, b, c) for a, rel in _co_graph.items() for b, c in rel.items()],
                key=lambda x: -x[2],
            )[:10]
        ],
    }
