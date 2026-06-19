# agent/runtime/tool_visibility_policy.py
"""Tool visibility policy — baseline, local-ops, and metadata helpers.

Extracted from tool_planner.py so the policy can be tested and referenced
independently without pulling in the full planner dependency tree.
"""

from __future__ import annotations

from typing import Any


# Baseline tools are read/search/list oriented. They are always injected.
BASELINE_READ_TOOLS = [
    "web.search", "web.page.summarize", "web.docs.official_search",
    "knowledge.search", "knowledge.source.list",
    "memory.search", "memory.list",
    "workspace.file.read", "workspace.file.list",
    "tool.catalog.search",
    "skill.list",
]

# Local execution tools are intentionally supported by the product, but they
# are exposed only when the routed scene explicitly requests local operations.
LOCAL_OPS_TOOLS = [
    "host.shell.exec", "host.powershell.exec", "host.python.exec",
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
