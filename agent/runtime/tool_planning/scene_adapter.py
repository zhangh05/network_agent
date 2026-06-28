# agent/runtime/tool_planning/scene_adapter.py
"""Scene adapter — converts SceneDecision to route_tool_scene-compatible dict.

Replaces the role of tool_category_router.py for downstream consumers.
"""

from __future__ import annotations

from typing import Any

from agent.runtime.cognition.scene_decision import SceneDecision


def scene_to_rule_scene(decision: SceneDecision) -> dict[str, Any]:
    """Convert a SceneDecision to the dict format expected by tool_planner."""
    primary_group = _primary_group(decision.primary_category, decision.groups)

    return {
        "primary_category": decision.primary_category,
        "categories": list(decision.categories),
        "groups": dict(decision.groups),
        "candidate_tools": [],  # populated by planner
        "tool_chain": [],       # populated by chain_builder
        "reason": decision.reason,
        "warnings": list(decision.warnings),
        "signals": dict(decision.signals),
        "allowed_actions": _allowed_actions(decision.user_input),
        "category": decision.primary_category,
        "group": primary_group,
        "followup_inherited": decision.followup_inherited,
    }


def _primary_group(primary_category: str, groups: dict[str, list[str]]) -> str:
    preferred = {
        "host": "shell",
        "workspace": "file",
        "network": "config",
        "web": "docs",
        "knowledge": "query",
        "runtime": "run",
        "memory": "profile",
        "report_data": "report",
        "agent": "agent",
    }
    group_ids = groups.get(primary_category, [])
    pref = preferred.get(primary_category)
    if pref in group_ids:
        return pref
    return group_ids[0] if group_ids else "general"


def _allowed_actions(user_input: str) -> list[str]:
    lower = (user_input or "").lower()
    allowed: set[str] = set()
    if any(k in lower for k in ("添加设备", "新增设备", "录入设备", "add device", "create device")):
        allowed.add("device.add")
    if any(k in lower for k in ("删除设备", "移除设备", "delete device", "remove device")):
        allowed.add("device.delete")
    if any(k in lower for k in ("保存", "导出", "生成报告", "save", "export", "render report")):
        allowed.update({"workspace.artifact.save", "report.artifact.save", "report.markdown.render"})
    if any(k in lower for k in ("修改文件", "编辑文件", "写入文件", "patch file", "edit file", "write file")):
        allowed.update({"workspace.file.edit", "workspace.file.patch", "workspace.file.write_artifact"})
    return sorted(allowed)
