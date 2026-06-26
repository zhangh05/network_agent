# agent/runtime/capability_routing/toolset.py
"""Build a small visible tool bundle for one turn.

v3.3: Hybrid retrieval — capability keyword matching + semantic embedding
search fused via RRF. Supports defer_loading mode where non-core tools
are emitted as compact name+one-liner descriptions instead of full schemas.
"""

from __future__ import annotations

from typing import Any

from tool_runtime.tool_governance import is_planner_visible
from tool_runtime.tool_namespace import TOOL_NAMESPACE

from .manifests import CORE_TOOL_IDS
from .models import ToolBundle
from .router import route_capabilities


DEFAULT_TOOL_LIMIT = 24  # baseline + routing headroom


def _valid_tool_ids(tool_ids) -> tuple[str, ...]:
    out: list[str] = []
    for tool_id in tool_ids:
        if tool_id in TOOL_NAMESPACE and is_planner_visible(tool_id) and tool_id not in out:
            out.append(tool_id)
    return tuple(out)


def build_active_tool_bundle(
    user_input: str,
    *,
    scene: Any = None,
    safe_context: dict | None = None,
    limit: int = DEFAULT_TOOL_LIMIT,
    use_hybrid: bool = True,
) -> ToolBundle:
    # ── 1. Capability keyword routing (always run) ──
    route = route_capabilities(user_input, scene=scene, safe_context=safe_context, limit=3)
    capability_tools: list[str] = []
    for package in route.packages:
        capability_tools.extend(package.tool_ids)

    # v3.8: Semantic routing boost — pick capabilities by embedding similarity
    semantic_id = None
    try:
        from agent.runtime.capability_routing.semantic_router import semantic_route
        from .manifests import CAPABILITY_PACKAGES
        cap_map = {p.capability_id: p.description for p in CAPABILITY_PACKAGES}
        semantic_id = semantic_route(user_input, cap_map)
    except Exception:
        pass

    # If semantic matched a different capability, add its tools too
    if semantic_id and semantic_id not in route.capability_ids:
        for package in CAPABILITY_PACKAGES:
            if package.capability_id == semantic_id:
                capability_tools.extend(package.tool_ids)
                route.capability_ids.add(semantic_id)
                break

    core_tools = _valid_tool_ids(CORE_TOOL_IDS)
    scoped_tools = _valid_tool_ids(capability_tools)

    # ── 2. Hybrid semantic retrieval (boost discovery) ──
    hybrid_tool_ids: list[str] = []
    hybrid_scores: dict[str, float] = {}
    if use_hybrid:
        try:
            from agent.runtime.tool_planning.hybrid_retriever import hybrid_tool_search
            hybrid_results = hybrid_tool_search(user_input, top_k=50)
            # Keep top 10 hybrid results that aren't already in core/capability
            already_seen = set(core_tools) | set(scoped_tools)
            for tid, score in hybrid_results:
                if tid not in already_seen and len(hybrid_tool_ids) < 10:
                    hybrid_tool_ids.append(tid)
                    hybrid_scores[tid] = score
        except Exception:
            pass

    scoped_hybrid = _valid_tool_ids(list(scoped_tools) + hybrid_tool_ids)
    total_unique = len(dict.fromkeys([*core_tools, *scoped_hybrid]))

    bundle = ToolBundle(
        core_tools=core_tools,
        capability_tools=scoped_hybrid,
        capability_ids=route.capability_ids,
        module_ids=route.module_ids,
        tool_limit=limit,
        metadata={
            "routing_mode": "hybrid" if hybrid_tool_ids else "capability_first",
            "route_reasons": dict(route.reasons),
            "route_confidence": dict(route.confidence),
            "core_tool_count": len(core_tools),
            "capability_tool_count": len(scoped_hybrid),
            "hybrid_tool_count": len(hybrid_tool_ids),
            "hybrid_scores": {k: round(v, 4) for k, v in hybrid_scores.items()},
            "route": route.to_dict(),
            "truncated": total_unique > limit,
        },
    )
    bundle.metadata["visible_tool_count"] = len(bundle.visible_tools)
    return bundle


def active_tool_catalog(
    user_input: str,
    *,
    scene: Any = None,
    safe_context: dict | None = None,
    limit: int = DEFAULT_TOOL_LIMIT,
) -> dict:
    bundle = build_active_tool_bundle(
        user_input, scene=scene, safe_context=safe_context, limit=limit,
    )
    return {
        "tools": bundle.visible_tools,
        "capability_routing": {
            "capability_ids": list(bundle.capability_ids),
            "module_ids": list(bundle.module_ids),
            **bundle.metadata,
        },
    }

