"""v2.2.2 intelligent tool planner.

The planner starts from the v2.2.1 rule_scene safety seed, builds a minimal
canonical tool plan, validates it, and falls back to the rule plan on any
invalid or unavailable planner output.

v3.1 optimizations:
- Added LRU-like namespace cache for repeated get_namespace_entry calls
- Removed redundant deterministic_plan_from_rule_scene (same as deterministic_plan_tools)
- Consolidated validate_tool_plan to reduce duplicate iteration
- Streamlined _capability_steps_from_rule_scene with keyword-driven dispatch
"""

from __future__ import annotations

import os
from functools import lru_cache
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


PLANNER_VERSION = "v2.4"
MAX_CANDIDATE_TOOLS = 24

# Baseline tools must remain read/search/list oriented. Local execution tools
# are intentionally supported by the product, but they are exposed only when
# the routed scene explicitly requests local operations / diagnostics.
#
# v3.3: Policy constants and helpers live in tool_planning/visibility.py.
from agent.runtime.tool_planning.visibility import (
    BASELINE_READ_TOOLS,
    LOCAL_OPS_TOOLS,
    scene_allows_local_ops,
    build_visibility_metadata,
)

# ─── v3.1: Cached namespace lookup ────────────────────────────────────

@lru_cache(maxsize=128)
def _cached_namespace_entry(tool_id: str):
    """Cached wrapper for get_namespace_entry to avoid repeated lookups."""
    try:
        return get_namespace_entry(tool_id)
    except Exception:
        return None


@lru_cache(maxsize=128)
def _cached_governance_entry(tool_id: str):
    """Cached wrapper for get_governance_entry."""
    try:
        return get_governance_entry(tool_id)
    except Exception:
        from tool_runtime.tool_governance import GovernanceEntry
        return GovernanceEntry(status="unknown")
# ─── Main planner entry point ─────────────────────────────────────────


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
        # Re-generate with fresh canonical-only filter
        seed = deterministic_plan_tools(user_input, safe_context, rule_scene, available_catalog)
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
        "non_active_tools_filtered": [],
        "unknown_tools_filtered": [],
        "local_ops_filtered": [],
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
            list(rule_scene.get("candidate_tools", [])),
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
    # v2.3.2: action_class filter — remove destructive actions unless the
    # scene explicitly allows them. Unknown tools are fail-closed.
    candidate_tools = _action_class_filter(candidate_tools, rule_scene)

    local_ops_enabled = scene_allows_local_ops(rule_scene, user_input)
    baseline_tools = list(BASELINE_READ_TOOLS)
    if local_ops_enabled:
        baseline_tools.extend(LOCAL_OPS_TOOLS)
    else:
        filtered["local_ops_filtered"].extend([tid for tid in LOCAL_OPS_TOOLS if tid in available])

    # Baseline injection is now read/search/list only unless the scene is local_ops.
    # This preserves shell/PowerShell as an explicit product capability while
    # preventing them from contaminating simple chat, knowledge QA, translation,
    # report, and offline file-analysis scenes.
    candidate_tools = _ordered_unique([*candidate_tools, *baseline_tools])
    candidate_tools = _governance_filtered_tools([tid for tid in candidate_tools if tid in available], filtered)

    # v2.4: Strip local ops tools from ALL candidate sources when the scene
    # does not request local operations — not just from baseline injection.
    # This prevents scene-supplied candidates from smuggling in shell/exec.
    if not local_ops_enabled:
        _local_ops_set = set(LOCAL_OPS_TOOLS)
        _stripped = [t for t in candidate_tools if t in _local_ops_set]
        candidate_tools = [t for t in candidate_tools if t not in _local_ops_set]
        if _stripped:
            filtered.setdefault("local_ops_filtered", [])
            filtered["local_ops_filtered"].extend(_stripped)
            filtered["local_ops_filtered"] = _ordered_unique(filtered["local_ops_filtered"])

    # v2.3.3: Safety net — auto-inject workspace.file.read when config
    # parsing tools are selected but file reading tools are missing.
    _has_config_tools = {"network.config.parse", "network.config.translate",
                         "network.interface.extract", "network.route.extract"} & set(candidate_tools)
    _has_file_tools = {"workspace.file.read", "workspace.file.preview",
                       "workspace.file.list"} & set(candidate_tools)
    if _has_config_tools and not _has_file_tools:
        candidate_tools = _ordered_unique(["workspace.file.list", "workspace.file.read", *candidate_tools])

    needs_clarification = _needs_file_clarification(user_input, safe_context, rule_scene)

    if needs_clarification and not {"workspace.file.read", "workspace.file.preview"} & set(candidate_tools):
        candidate_tools = _ordered_unique(["workspace.file.list", *candidate_tools])

    categories, groups = _categories_groups_from_tools(candidate_tools, rule_scene)
    primary = rule_scene.get("primary_category") or rule_scene.get("category") or (categories[0] if categories else "web")
    group = rule_scene.get("group") or (groups.get(primary) or ["general"])[0]
    visibility_meta = build_visibility_metadata(
        rule_scene=rule_scene,
        candidate_tools=candidate_tools,
        baseline_tools=baseline_tools,
        local_ops_enabled=local_ops_enabled,
        filtered=filtered,
    )
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
        "visibility": visibility_meta,
        "needs_clarification": needs_clarification,
        "clarifying_question": "请提供要分析的配置文件路径，或先上传配置文件。" if needs_clarification else "",
        "reason": rule_scene.get("reason", "deterministic planner from rule_scene"),
        "category": primary,
        "group": group,
    }
    plan["tool_chain"] = _tool_chain_from_plan(steps)
    return plan



def llm_plan_tools(
    user_input: str,
    safe_context: dict | None,
    seed_plan: dict,
    available_catalog: dict,
    model_config: dict | None = None,
) -> dict | None:
    """Optional LLM planner hook — fail-closed until dedicated adapter is wired."""
    if not model_config or not model_config.get("enabled"):
        return None
    return None


# v3.3: validate_tool_plan moved to tool_planning/validation.py.
from agent.runtime.tool_planning.validation import validate_tool_plan


# ─── v3.1: Keyword-driven capability dispatch ─────────────────────────

# Map signal keywords to (capability_action_id, goal_template)
_SIGNAL_DISPATCH = [
    (("has_uploaded_files", "mentions_file"), "workspace.file.read", "读取上传或 workspace 中的文本文件"),
    (("has_uploaded_files", "mentions_image"), "workspace.file.read_image", "读取上传图片的尺寸/格式元数据"),
    (("mentions_web",), "web.official_docs.search", "检索官方文档或外部资料"),
    (("mentions_weather",), "web.weather.read", "查询天气信息"),
    (("mentions_knowledge",), "knowledge.search_and_answer", "检索知识库并基于安全摘录回答"),
    (("mentions_config_translate",), "network.config.translate", "离线翻译网络配置"),
    (("mentions_packet",), "network.pcap.analyze", "离线分析 PCAP 报文、连接和 TCP 序列"),
    (("mentions_network_config",), "network.config.analyze", "离线分析网络配置"),
    (("mentions_report",), "report.create_and_save", "生成报告并保存制品"),
    (("mentions_host",), "host.environment.inspect", "查询或操作当前本机环境"),
    (("mentions_runtime",), "runtime.audit.inspect", "查看运行、trace、session 或审计信息"),
    (("mentions_memory",), "memory.profile.manage", "搜索或维护记忆/profile"),
    # v3.1.1: sub-agent coordination for complex/parallel tasks
    (("mentions_sub_agent",), "agent.team.coordinate", "派生子代理并行处理复杂任务"),
]


def _capability_steps_from_rule_scene(user_input: str, rule_scene: dict) -> list[dict[str, Any]]:
    """Build capability steps from rule_scene signals.

    v3.1: Uses keyword-driven dispatch instead of repeated if/elif.
    v3.1.1: sub-agent coordination is exposed only when the scene detects a
    complex / parallel / delegated task, not as a universal baseline.
    """
    signals = rule_scene.get("signals") or {}
    steps: list[dict[str, Any]] = []
    seen_actions: set[str] = set()

    def add(action_id: str, goal: str) -> None:
        if action_id in CAPABILITY_ACTIONS and action_id not in seen_actions:
            seen_actions.add(action_id)
            steps.append({
                "step": len(steps) + 1,
                "capability_action": action_id,
                "goal": goal,
                "preferred_tools": [],
            })

    for signal_keys, action_id, goal in _SIGNAL_DISPATCH:
        if any(signals.get(k) for k in signal_keys):
            add(action_id, goal)

    # Special cases that depend on user_input text
    lower = (user_input or "").lower()
    if ("translate" in lower or "翻译" in lower) and "network.config.translate" in CAPABILITY_ACTIONS:
        add("network.config.translate", "离线翻译网络配置")

    if not steps:
        for chain_step in rule_scene.get("tool_chain") or []:
            tools = list(chain_step.get("preferred_tools") or [])
            action_id = action_for_tool_set(tools)
            add(action_id, chain_step.get("purpose") or f"执行能力动作 {action_id}")
    return steps



# ─── Tool filtering & helpers ─────────────────────────────────────────


def _governance_filtered_tools(tool_ids: list[str], filtered: dict[str, list[str]]) -> list[str]:
    """v3.0 canonical-only governance filter.

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
    mentions_file = any(k in lower for k in (
        "这个配置文件", "这个文件", "上传的", "上传文件", "配置文件",
        "日志文件", "文件", "this config file", "this file", "uploaded file",
        "这个配置", "这份配置", "那个配置", "帮我看", "帮我分析",
        "看看这个", "看一下", "检查一下这个",
    ))
    wants_analysis = any(k in lower for k in (
        "分析", "检查", "看看", "整理", "报告", "parse", "analyze", "review",
        "解析", "提取", "翻译", "转换",
    ))
    signals = rule_scene.get("signals", {}) or {}
    has_upload = bool(safe_context.get("uploaded_files") or signals.get("has_uploaded_files"))
    has_refs = bool(
        safe_context.get("artifact_refs")
        or safe_context.get("workspace_state")
        or safe_context.get("source_config_artifact_id")
        or safe_context.get("context_sources")
    )
    return bool(mentions_file and wants_analysis and not has_upload and not has_refs)


def _categories_groups_from_tools(candidate_tools: list[str], rule_scene: dict) -> tuple[list[str], dict[str, list[str]]]:
    """v3.1: Uses cached namespace lookups."""
    categories: list[str] = []
    groups: dict[str, list[str]] = {}
    for tool_id in candidate_tools:
        entry = _cached_namespace_entry(tool_id)
        if entry is None:
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
    out.setdefault("governance", {"non_active_tools_filtered": [], "unknown_tools_filtered": [], "local_ops_filtered": []})
    out.setdefault("visibility", {})
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


def _action_class_filter(candidate_tools: list[str], rule_scene: dict) -> list[str]:
    """Filter candidate tools by action_class.

    v2.4 hardening: unknown tools fail closed. Destructive mutations are held
    back unless the scene explicitly allows them. High-risk local ops still
    go through the approval gate when deliberately exposed.
    """
    from tool_runtime.action_class import classify_tool
    from tool_runtime.tool_namespace import TOOL_NAMESPACE

    result = []
    for tid in candidate_tools:
        entry = TOOL_NAMESPACE.get(tid)
        if entry is None:
            continue
        ac = classify_tool(tid, entry.category, entry.group, entry.action)

        # Only filter truly destructive actions that require explicit user intent
        if ac.is_destructive and not _user_wants_destructive(rule_scene, tid):
            continue

        result.append(tid)

    return result


def _user_wants_destructive(rule_scene: dict, tool_id: str) -> bool:
    """Check if the user's explicit request justifies a destructive tool."""
    allowed = set(rule_scene.get("allowed_actions") or [])
    if tool_id in allowed:
        return True
    # Destructive maintenance ops and profile/team coordination
    # require explicit scene allowlist entry.
    return False
