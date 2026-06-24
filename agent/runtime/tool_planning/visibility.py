# agent/runtime/tool_planning/visibility.py
"""Tool visibility policy — baseline, local-ops, governance filtering, and metadata helpers.

Canonical location for all tool-visibility logic.
"""

from __future__ import annotations

from typing import Any

from tool_runtime.tool_governance import is_planner_visible
from tool_runtime.tool_namespace import TOOL_NAMESPACE


BASELINE_READ_TOOLS = [
    # v3.2: skill.load / skill.search removed.
    # Use tool.catalog.search for tool discovery.
    "tool.catalog.search",
    "workspace.file.list", "workspace.file.read",
    "workspace.artifact.read",
    # Host
    "host.shell.exec", "host.powershell.exec",
    "host.python.exec", "host.command.slash_run",
    # Web
    "web.search", "web.docs.official_search",
    "web.page.summarize", "web.page.extract_links",
    "web.page.save_artifact",
    "web.news.search",
    "web.weather",
]

LOCAL_OPS_TOOLS = [
    "runtime.health", "runtime.diagnostics",
]


def scene_allows_local_ops(rule_scene: dict, user_input: str) -> bool:
    """Return True when the scene explicitly requests local-machine operations."""
    signals = rule_scene.get("signals") or {}
    if signals.get("mentions_host"):
        return True
    categories = set(rule_scene.get("categories") or [])
    if "host" in categories:
        return True
    groups = rule_scene.get("groups") or {}
    if groups.get("host"):
        return True
    lower = (user_input or "").lower()
    explicit = (
        "本机", "localhost", "127.0.0.1", "shell", "powershell", "cmd",
        "执行命令", "跑命令", "运行命令", "终端", "命令行", "ipconfig",
        "ifconfig", "netstat", "process", "进程", "端口", "磁盘", "内存",
        "cpu", "system info", "启动服务", "停止服务",
    )
    return any(k in lower for k in explicit)


def build_visibility_metadata(
    *,
    rule_scene: dict,
    candidate_tools: list[str],
    baseline_tools: list[str],
    local_ops_enabled: bool,
    filtered: dict[str, list[str]],
) -> dict[str, Any]:
    """Build the visibility metadata dict attached to every tool plan."""
    return {
        "scene": rule_scene.get("primary_category") or rule_scene.get("category") or "unknown",
        "reason": rule_scene.get("reason", ""),
        "candidate_count": len(candidate_tools),
        "local_ops_enabled": bool(local_ops_enabled),
        "baseline_tools_added": list(baseline_tools),
        "visible_tools": list(candidate_tools),
        "filtered": dict(filtered),
    }


# ─── Governance filtering ──────────────────────────────────────────────


def _ordered_unique(items) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def governance_filtered_tools(tool_ids: list[str], filtered: dict[str, list[str]]) -> list[str]:
    """Canonical-only governance filter.

    Keeps planner-visible canonical tools and records filtered
    (non-active / non-canonical) ids under governance fields.
    Unknown tools fail closed instead of passing through.
    """
    result: list[str] = []
    for tool_id in tool_ids:
        if tool_id not in TOOL_NAMESPACE:
            filtered.setdefault("unknown_tools_filtered", []).append(tool_id)
            continue
        if not is_planner_visible(tool_id):
            filtered.setdefault("non_active_tools_filtered", []).append(tool_id)
            continue
        if tool_id not in result:
            result.append(tool_id)
    filtered["non_active_tools_filtered"] = _ordered_unique(
        filtered.get("non_active_tools_filtered", []),
    )
    filtered["unknown_tools_filtered"] = _ordered_unique(
        filtered.get("unknown_tools_filtered", []),
    )
    filtered["local_ops_filtered"] = _ordered_unique(
        filtered.get("local_ops_filtered", []),
    )
    return result


def available_canonical_tools(available_catalog: dict) -> set[str]:
    """Compute the set of available canonical tool IDs."""
    tools = available_catalog.get("tools") if isinstance(available_catalog, dict) else None
    if tools:
        return {str(t) for t in tools if str(t) in TOOL_NAMESPACE}
    return set(TOOL_NAMESPACE)


def action_class_filter(candidate_tools: list[str], rule_scene: dict) -> list[str]:
    """Filter candidate tools by action_class.

    Unknown tools fail closed. Destructive mutations are held
    back unless the scene explicitly allows them.
    """
    from tool_runtime.action_class import classify_tool

    result = []
    for tid in candidate_tools:
        entry = TOOL_NAMESPACE.get(tid)
        if entry is None:
            continue
        ac = classify_tool(tid, entry.category, entry.group, entry.action)
        if ac.is_destructive and not user_wants_destructive(rule_scene, tid):
            continue
        result.append(tid)
    return result


def user_wants_destructive(rule_scene: dict, tool_id: str) -> bool:
    """Check if the user's explicit request justifies a destructive tool."""
    allowed = set(rule_scene.get("allowed_actions") or [])
    if tool_id in allowed:
        return True
    return False
