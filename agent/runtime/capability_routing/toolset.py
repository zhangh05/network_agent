# agent/runtime/capability_routing/toolset.py
"""Build a small visible tool bundle for one turn."""

from __future__ import annotations

from typing import Any

from tool_runtime.tool_governance import is_planner_visible
from tool_runtime.tool_namespace import TOOL_NAMESPACE

from .manifests import CORE_TOOL_IDS
from .models import ToolBundle
from .router import route_capabilities


DEFAULT_TOOL_LIMIT = 24  # 17 baseline + routing headroom


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
) -> ToolBundle:
    route = route_capabilities(user_input, scene=scene, safe_context=safe_context, limit=3)
    capability_tools: list[str] = []
    for package in route.packages:
        capability_tools.extend(package.tool_ids)
    core_tools = _valid_tool_ids(CORE_TOOL_IDS)
    scoped_tools = _valid_tool_ids(capability_tools)
    total_unique = len(dict.fromkeys([*core_tools, *scoped_tools]))
    bundle = ToolBundle(
        core_tools=core_tools,
        capability_tools=scoped_tools,
        capability_ids=route.capability_ids,
        module_ids=route.module_ids,
        tool_limit=limit,
        metadata={
            "routing_mode": "capability_first",
            "route_reasons": dict(route.reasons),
            "route_confidence": dict(route.confidence),
            "core_tool_count": len(core_tools),
            "capability_tool_count": len(scoped_tools),
            "route": route.to_dict(),
            "truncated": total_unique > limit,
        },
    )
    bundle.metadata["visible_tool_count"] = len(bundle.visible_tools)
    return bundle


def active_tool_catalog(user_input: str, *, scene: Any = None, safe_context: dict | None = None, limit: int = DEFAULT_TOOL_LIMIT) -> dict:
    bundle = build_active_tool_bundle(user_input, scene=scene, safe_context=safe_context, limit=limit)
    return {
        "tools": bundle.visible_tools,
        "capability_routing": {
            "capability_ids": list(bundle.capability_ids),
            "module_ids": list(bundle.module_ids),
            **bundle.metadata,
        },
    }
