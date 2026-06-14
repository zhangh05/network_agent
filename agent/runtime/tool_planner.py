"""v2.2.2 intelligent tool planner.

The planner starts from the v2.2.1 rule_scene safety seed, builds a minimal
canonical tool plan, validates it, and falls back to the rule plan on any
invalid or unavailable planner output.
"""

from __future__ import annotations

import os
from typing import Any, TypedDict

from tool_runtime.capability_actions import (
    CAPABILITY_ACTIONS,
    action_exists,
    action_for_tool_set,
    tools_for_action,
)
from tool_runtime.tool_governance import get_governance_entry, is_planner_visible
from tool_runtime.tool_namespace import TOOL_NAMESPACE, get_namespace_entry


class ToolPlanStep(TypedDict, total=False):
    step: int
    goal: str
    tool_candidates: list[str]
    required: bool
    depends_on: list[int]
    stop_if_failed: bool


class ToolPlan(TypedDict, total=False):
    planner_version: str
    mode: str
    primary_category: str
    categories: list[str]
    groups: dict[str, list[str]]
    candidate_tools: list[str]
    tool_plan: list[ToolPlanStep]
    tool_chain: list[dict[str, Any]]
    needs_clarification: bool
    clarifying_question: str
    reason: str
    category: str
    group: str
    tool_planner: dict[str, Any]


PLANNER_VERSION = "v2.3"
MAX_CANDIDATE_TOOLS = 16


def plan_tools(
    user_input: str,
    safe_context: dict | None,
    rule_scene: dict,
    available_catalog: dict,
    model_config: dict | None = None,
) -> dict:
    """Return a validated tool plan, falling back to deterministic seed."""
    mode = os.environ.get("TOOL_PLANNER_MODE", "hybrid").strip().lower() or "hybrid"
    if mode not in {"deterministic", "llm", "hybrid"}:
        mode = "hybrid"

    available = _available_canonical_tools(available_catalog)
    seed = deterministic_plan_tools(user_input, safe_context, rule_scene, available_catalog)
    seed_valid, seed_messages = validate_tool_plan(seed, available, user_input=user_input)
    if not seed_valid:
        seed = deterministic_plan_from_rule_scene(user_input, safe_context, rule_scene, available_catalog)
        seed_valid, seed_messages = validate_tool_plan(seed, available, user_input=user_input)

    plan = seed
    fallback_used = False
    validation_messages = list(seed_messages)

    if mode in {"llm", "hybrid"}:
        llm_plan = llm_plan_tools(user_input, safe_context, seed, available_catalog, model_config)
        if llm_plan:
            valid, messages = validate_tool_plan(llm_plan, available, user_input=user_input)
            if valid:
                plan = _finalize_plan(llm_plan, mode=mode, valid=True, fallback_used=False, warnings=messages)
                return plan
            fallback_used = True
            validation_messages.extend(messages)
        elif mode == "llm":
            fallback_used = True
            validation_messages.append("llm_planner_unavailable")

    return _finalize_plan(
        plan,
        mode="deterministic" if mode == "deterministic" else mode,
        valid=seed_valid,
        fallback_used=fallback_used,
        warnings=validation_messages,
    )


def deterministic_plan_tools(
    user_input: str,
    safe_context: dict | None,
    rule_scene: dict,
    available_catalog: dict,
) -> dict:
    """Build a minimal deterministic plan from the rule_scene chain."""
    available = _available_canonical_tools(available_catalog)
    safe_context = safe_context or {}
    capability_steps = _capability_steps_from_rule_scene(user_input, rule_scene)
    steps: list[dict[str, Any]] = []
    filtered: dict[str, list[str]] = {
        "deprecated_tools_filtered": [],
        "alias_tools_collapsed": [],
    }

    for capability_step in capability_steps:
        action_id = capability_step["capability_action"]
        raw_tools = tools_for_action(action_id, include_fallback=True, available=available)
        tools = _governance_filtered_tools(raw_tools, filtered)
        if not tools:
            continue
        step_no = len(steps) + 1
        required = _step_required(user_input, step_no, tools)
        steps.append({
            "step": step_no,
            "goal": capability_step.get("goal") or f"执行能力动作 {action_id}",
            "tool_candidates": tools,
            "required": required,
            "depends_on": list(range(1, step_no)) if step_no > 1 else [],
            "stop_if_failed": bool(required and step_no == 1),
        })
        capability_step["step"] = step_no
        capability_step["preferred_tools"] = tools

    capability_steps = [step for step in capability_steps if step.get("preferred_tools")]

    if not steps:
        tools = _governance_filtered_tools(
            [tid for tid in rule_scene.get("candidate_tools", []) if tid in available],
            filtered,
        )[:5]
        if tools:
            action_id = action_for_tool_set(tools)
            steps.append({
                "step": 1,
                "goal": "执行当前场景的首选工具",
                "tool_candidates": tools,
                "required": True,
                "depends_on": [],
                "stop_if_failed": True,
            })
            capability_steps = [{
                "step": 1,
                "capability_action": action_id,
                "goal": "执行当前场景的首选能力动作",
                "preferred_tools": tools,
            }]

    candidate_tools = _ordered_unique(
        tid
        for step in steps
        for tid in step.get("tool_candidates", [])
    )
    needs_clarification = _needs_file_clarification(user_input, safe_context, rule_scene)

    if needs_clarification and not {"workspace.file.read", "workspace.file.preview"} & set(candidate_tools):
        candidate_tools = _ordered_unique(["workspace.file.list", *candidate_tools])

    categories, groups = _categories_groups_from_tools(candidate_tools, rule_scene)
    primary = rule_scene.get("primary_category") or rule_scene.get("category") or (categories[0] if categories else "web")
    group = rule_scene.get("group") or (groups.get(primary) or ["general"])[0]
    plan = {
        "planner_version": PLANNER_VERSION,
        "mode": "deterministic",
        "primary_category": primary,
        "categories": categories,
        "groups": groups,
        "candidate_tools": candidate_tools,
        "capability_plan": capability_steps,
        "tool_plan": steps,
        "governance": filtered,
        "needs_clarification": needs_clarification,
        "clarifying_question": "请提供要分析的配置文件路径，或先上传配置文件。" if needs_clarification else "",
        "reason": rule_scene.get("reason", "deterministic planner from rule_scene"),
        "category": primary,
        "group": group,
    }
    plan["tool_chain"] = _tool_chain_from_plan(steps)
    return plan


def deterministic_plan_from_rule_scene(
    user_input: str,
    safe_context: dict | None,
    rule_scene: dict,
    available_catalog: dict,
) -> dict:
    return deterministic_plan_tools(user_input, safe_context, rule_scene, available_catalog)


def llm_plan_tools(
    user_input: str,
    safe_context: dict | None,
    seed_plan: dict,
    available_catalog: dict,
    model_config: dict | None = None,
) -> dict | None:
    """Optional LLM planner hook.

    v2.2.2 ships the deterministic planner as the reliable default. This hook
    is intentionally fail-closed until a dedicated planning provider adapter is
    wired; callers must fall back to the deterministic seed.
    """
    if not model_config or not model_config.get("enabled"):
        return None
    return None


def validate_tool_plan(
    plan: dict,
    available_canonical_tools: set[str],
    *,
    user_input: str = "",
) -> tuple[bool, list[str]]:
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
        f"{tid}:{get_governance_entry(tid).status}"
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
    capability_steps = [int(step.get("step", 0) or 0) for step in capability_plan]
    if capability_plan and capability_steps != expected_steps:
        errors.append(f"capability_steps_not_consecutive:{capability_steps}")
    for step in capability_plan:
        step_no = int(step.get("step", 0) or 0)
        action_id = str(step.get("capability_action", ""))
        if not action_exists(action_id):
            errors.append(f"capability_action_unknown:{action_id}")
        preferred = list(step.get("preferred_tools") or step.get("tools") or [])
        outside = [tid for tid in preferred if tid not in candidate_set]
        if outside:
            errors.append(f"capability_step_{step_no}_tools_not_in_candidates:{outside}")

    category_errors = _validate_categories_groups(plan, candidate_tools)
    errors.extend(category_errors)

    lower = (user_input or "").lower()
    network_request = any(k in lower for k in ("华三", "h3c", "cisco", "huawei", "juniper", "ospf", "bgp", "配置", "running-config", "network config"))
    explicit_host = any(k in lower for k in ("本机", "localhost", "shell", "powershell", "python", "ifconfig", "ipconfig", "netstat"))
    if network_request and not explicit_host and {"host.shell.exec", "host.powershell.exec"} & candidate_set:
        errors.append("network_plan_must_not_use_host_shell")

    file_analysis = any(k in lower for k in ("上传", "配置文件", "文件", "workspace", "pcap", "pdf"))
    if file_analysis and "分析" in lower and "network.config.parse" in candidate_set:
        if not {"workspace.file.read", "workspace.file.preview"} & candidate_set:
            errors.append("file_analysis_requires_workspace_read_or_preview")

    report_request = any(k in lower for k in ("报告", "整理", "保存", "导出", "制品", "artifact"))
    if report_request:
        if "report.markdown.render" not in candidate_set:
            errors.append("report_request_requires_report_markdown_render")
        if "workspace.artifact.save" not in candidate_set:
            errors.append("report_request_requires_workspace_artifact_save")

    return not errors, [*errors, *warnings]


def _capability_steps_from_rule_scene(user_input: str, rule_scene: dict) -> list[dict[str, Any]]:
    signals = rule_scene.get("signals") or {}
    steps: list[dict[str, Any]] = []

    def add(action_id: str, goal: str) -> None:
        if action_id in CAPABILITY_ACTIONS and action_id not in {s["capability_action"] for s in steps}:
            steps.append({
                "step": len(steps) + 1,
                "capability_action": action_id,
                "goal": goal,
                "preferred_tools": [],
            })

    if signals.get("has_uploaded_files") or signals.get("mentions_file"):
        add("workspace.file.read", "读取用户上传或 workspace 中的文件")
    if signals.get("mentions_web"):
        add("web.official_docs.search", "检索官方文档或外部资料")
    if signals.get("mentions_network_config"):
        add("network.config.analyze", "离线分析网络配置")
    if "translate" in (user_input or "").lower() or "翻译" in (user_input or ""):
        add("network.config.translate", "离线翻译网络配置")
    if signals.get("mentions_report"):
        add("report.create_and_save", "生成报告并保存制品")
    if signals.get("mentions_host"):
        add("host.environment.inspect", "查询或操作当前本机环境")
    if signals.get("mentions_knowledge"):
        add("knowledge.search_and_answer", "检索知识库并基于安全摘录回答")
    if signals.get("mentions_runtime"):
        add("runtime.audit.inspect", "查看运行、trace、session 或审计信息")
    if signals.get("mentions_memory"):
        add("memory.profile.manage", "搜索或维护记忆/profile")

    if not steps:
        for chain_step in rule_scene.get("tool_chain") or []:
            tools = list(chain_step.get("preferred_tools") or [])
            action_id = action_for_tool_set(tools)
            add(action_id, chain_step.get("purpose") or f"执行能力动作 {action_id}")
    return steps


def _governance_filtered_tools(tool_ids: list[str], filtered: dict[str, list[str]]) -> list[str]:
    result: list[str] = []
    for tool_id in tool_ids:
        if tool_id not in TOOL_NAMESPACE:
            continue
        entry = get_governance_entry(tool_id)
        if entry.status in {"alias", "merged"}:
            filtered.setdefault("alias_tools_collapsed", []).append(tool_id)
            replacement = entry.replacement
            if replacement and replacement in TOOL_NAMESPACE and is_planner_visible(replacement):
                if replacement not in result:
                    result.append(replacement)
            continue
        if entry.status in {"deprecated", "removed_candidate"}:
            filtered.setdefault("deprecated_tools_filtered", []).append(tool_id)
            continue
        if tool_id not in result:
            result.append(tool_id)
    for key in ("deprecated_tools_filtered", "alias_tools_collapsed"):
        filtered[key] = _ordered_unique(filtered.get(key, []))
    return result


def _available_canonical_tools(available_catalog: dict) -> set[str]:
    tools = available_catalog.get("tools") if isinstance(available_catalog, dict) else None
    if tools:
        return {str(t) for t in tools if str(t) in TOOL_NAMESPACE}
    return set(TOOL_NAMESPACE)


def _step_required(user_input: str, step_no: int, tools: list[str]) -> bool:
    if step_no == 1:
        return True
    if "network.config.parse" in tools:
        return True
    return False


def _needs_file_clarification(user_input: str, safe_context: dict, rule_scene: dict) -> bool:
    lower = (user_input or "").lower()
    mentions_this_file = "这个配置文件" in lower or "this config file" in lower
    has_upload = bool(safe_context.get("uploaded_files") or rule_scene.get("signals", {}).get("has_uploaded_files"))
    has_refs = bool(safe_context.get("artifact_refs") or safe_context.get("workspace_state"))
    return bool(mentions_this_file and not has_upload and not has_refs)


def _categories_groups_from_tools(candidate_tools: list[str], rule_scene: dict) -> tuple[list[str], dict[str, list[str]]]:
    categories: list[str] = []
    groups: dict[str, list[str]] = {}
    for tool_id in candidate_tools:
        try:
            entry = get_namespace_entry(tool_id)
        except Exception:
            continue
        if entry.category not in categories:
            categories.append(entry.category)
        groups.setdefault(entry.category, [])
        if entry.group not in groups[entry.category]:
            groups[entry.category].append(entry.group)
    for category in rule_scene.get("categories") or []:
        if category in groups and category not in categories:
            categories.append(category)
    return categories, groups


def _validate_categories_groups(plan: dict, candidate_tools: list[str]) -> list[str]:
    errors: list[str] = []
    categories = set(plan.get("categories") or [])
    groups = plan.get("groups") or {}
    for tool_id in candidate_tools:
        if tool_id not in TOOL_NAMESPACE:
            continue
        entry = get_namespace_entry(tool_id)
        if entry.category not in categories:
            errors.append(f"tool_category_missing:{tool_id}:{entry.category}")
        if entry.group not in set(groups.get(entry.category, [])):
            errors.append(f"tool_group_missing:{tool_id}:{entry.category}.{entry.group}")
    return errors


def _tool_chain_from_plan(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "step": step.get("step"),
            "purpose": step.get("goal", ""),
            "preferred_tools": list(step.get("tool_candidates") or []),
        }
        for step in steps
    ]


def _finalize_plan(plan: dict, *, mode: str, valid: bool, fallback_used: bool, warnings: list[str]) -> dict:
    out = dict(plan)
    out["planner_version"] = PLANNER_VERSION
    out["mode"] = mode
    out.setdefault("needs_clarification", False)
    out.setdefault("clarifying_question", "")
    out.setdefault("tool_chain", _tool_chain_from_plan(out.get("tool_plan") or []))
    out.setdefault("capability_plan", [])
    out.setdefault("governance", {"deprecated_tools_filtered": [], "alias_tools_collapsed": []})
    out.setdefault("category", out.get("primary_category", ""))
    out.setdefault("group", (out.get("groups", {}).get(out.get("primary_category", ""), ["general"]) or ["general"])[0])
    out["tool_planner"] = {
        "planner_version": PLANNER_VERSION,
        "mode": mode,
        "valid": valid,
        "fallback_used": fallback_used,
        "warnings": warnings,
    }
    return out


def _ordered_unique(items) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result
