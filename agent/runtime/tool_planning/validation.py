# agent/runtime/tool_planning/validation.py
"""Tool plan validation — moved from tool_planner.py::validate_tool_plan.

Canonical location for plan validation logic.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from tool_runtime.capability_actions import action_exists
from tool_runtime.tool_governance import get_governance_entry, is_planner_visible
from tool_runtime.tool_namespace import TOOL_NAMESPACE, get_namespace_entry

MAX_CANDIDATE_TOOLS = 24


@lru_cache(maxsize=128)
def _cached_namespace_entry(tool_id: str):
    try:
        return get_namespace_entry(tool_id)
    except Exception:
        return None


@lru_cache(maxsize=128)
def _cached_governance_entry(tool_id: str):
    try:
        return get_governance_entry(tool_id)
    except Exception:
        from tool_runtime.tool_governance import GovernanceEntry
        return GovernanceEntry(status="unknown")


def validate_tool_plan(
    plan: dict,
    available_canonical_tools: set[str],
    *,
    user_input: str = "",
) -> tuple[bool, list[str]]:
    """Validate a tool plan. Returns (is_valid, messages)."""
    errors: list[str] = []
    warnings: list[str] = []
    candidate_tools = list(plan.get("candidate_tools") or [])
    candidate_set = set(candidate_tools)

    missing = [tid for tid in candidate_tools if tid not in available_canonical_tools]
    if missing:
        errors.append(f"candidate_tools_not_canonical_or_unknown:{missing}")

    if len(candidate_tools) != len(candidate_set):
        errors.append("candidate_tools_duplicate")
    if len(candidate_tools) > MAX_CANDIDATE_TOOLS:
        warnings.append(f"candidate_tools_large:{len(candidate_tools)}")

    governed_out = [
        f"{tid}:{_cached_governance_entry(tid).status}"
        for tid in candidate_tools
        if tid in available_canonical_tools and not is_planner_visible(tid)
    ]
    if governed_out:
        errors.append(f"governance_not_planner_visible:{governed_out}")

    steps = list(plan.get("tool_plan") or [])
    expected_steps = list(range(1, len(steps) + 1))
    actual_steps = [int(step.get("step", 0) or 0) for step in steps]
    if actual_steps != expected_steps:
        errors.append(f"steps_not_consecutive:{actual_steps}")

    for step in steps:
        step_no = int(step.get("step", 0) or 0)
        tools = list(step.get("tool_candidates") or [])
        outside = [tid for tid in tools if tid not in candidate_set]
        if outside:
            errors.append(f"step_{step_no}_tools_not_in_candidates:{outside}")
        unknown = [tid for tid in tools if tid not in available_canonical_tools]
        if unknown:
            errors.append(f"step_{step_no}_tools_unknown:{unknown}")
        deps = list(step.get("depends_on") or [])
        bad_deps = [dep for dep in deps if not isinstance(dep, int) or dep >= step_no or dep < 1]
        if bad_deps:
            errors.append(f"step_{step_no}_invalid_depends_on:{bad_deps}")

    capability_plan = list(plan.get("capability_plan") or [])
    capability_steps_list = [int(step.get("step", 0) or 0) for step in capability_plan]
    if capability_plan and capability_steps_list != expected_steps:
        errors.append(f"capability_steps_not_consecutive:{capability_steps_list}")
    for step in capability_plan:
        step_no = int(step.get("step", 0) or 0)
        action_id = str(step.get("capability_action", ""))
        if not action_exists(action_id):
            errors.append(f"capability_action_unknown:{action_id}")
        preferred = list(step.get("preferred_tools") or step.get("tools") or [])
        outside = [tid for tid in preferred if tid not in candidate_set]
        if outside:
            errors.append(f"capability_step_{step_no}_tools_not_in_candidates:{outside}")

    errors.extend(_validate_categories_groups(plan, candidate_tools))
    errors.extend(_semantic_checks(user_input, candidate_set))

    return not errors, [*errors, *warnings]


def _validate_categories_groups(plan: dict, candidate_tools: list[str]) -> list[str]:
    errors: list[str] = []
    categories = set(plan.get("categories") or [])
    groups = plan.get("groups") or {}
    for tool_id in candidate_tools:
        if tool_id not in TOOL_NAMESPACE:
            continue
        entry = _cached_namespace_entry(tool_id)
        if entry is None:
            continue
        if entry.category not in categories:
            errors.append(f"tool_category_missing:{tool_id}:{entry.category}")
        if entry.group not in set(groups.get(entry.category, [])):
            errors.append(f"tool_group_missing:{tool_id}:{entry.category}.{entry.group}")
    return errors


def _semantic_checks(user_input: str, candidate_set: set[str]) -> list[str]:
    """Domain-specific semantic validation rules."""
    errors: list[str] = []
    lower = (user_input or "").lower()

    network_request = any(k in lower for k in ("华三", "h3c", "cisco", "huawei", "juniper",
                                                 "ospf", "bgp", "配置", "running-config", "network config"))
    explicit_host = any(k in lower for k in ("本机", "localhost", "shell", "powershell",
                                              "python", "ifconfig", "ipconfig", "netstat"))
    if network_request and not explicit_host and {"host.shell.exec", "host.powershell.exec"} & candidate_set:
        errors.append("network_plan_must_not_use_host_shell")

    file_analysis = any(k in lower for k in ("上传", "配置文件", "文件", "workspace", "pcap", "pdf",
                                              "这个配置", "这份配置", "帮我看", "帮我分析"))
    analysis_keywords = any(k in lower for k in ("分析", "解析", "检查", "提取", "看看", "review", "analyze"))
    if (file_analysis and analysis_keywords and "config.analysis.run" in candidate_set):
        if not {"workspace.file.read", "workspace.file.preview"} & candidate_set:
            errors.append("file_analysis_requires_workspace_read_or_preview")

    packet_request = any(k in lower for k in ("pcap", "pcapng", "报文", "抓包", "五元组", "tcp流", "tcp 流", "重传", "乱序", "seq gap"))
    if packet_request and "pcap.analysis.run" in candidate_set:
        if "workspace.file.read" not in candidate_set:
            errors.append("pcap_request_requires_workspace_read")

    report_request = any(k in lower for k in ("报告", "整理", "保存", "导出", "制品", "artifact"))
    if report_request:
        if "report.markdown.render" not in candidate_set:
            errors.append("report_request_requires_report_markdown_render")
        if "workspace.artifact.save" not in candidate_set:
            errors.append("report_request_requires_workspace_artifact_save")

    return errors
