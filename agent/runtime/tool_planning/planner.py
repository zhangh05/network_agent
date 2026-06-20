# agent/runtime/tool_planning/planner.py
"""ToolPlannerV2 + deterministic planner — canonical planner for the cognition layer.

All core planner logic migrated from agent/runtime/tool_planner.py.
Uses SceneDecision + EvidenceBundle to produce a validated tool plan.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from tool_runtime.capability_actions import (
    CAPABILITY_ACTIONS,
    action_for_tool_set,
    tools_for_action,
)
from tool_runtime.tool_governance import get_governance_entry
from tool_runtime.tool_namespace import get_namespace_entry

from agent.runtime.cognition.scene_decision import SceneDecision
from agent.runtime.tool_planning.chain_builder import (
    SIGNAL_DISPATCH,
    categories_groups_from_tools,
    tool_chain_from_plan,
)
from agent.runtime.tool_planning.scene_adapter import scene_to_rule_scene
from agent.runtime.tool_planning.validation import validate_tool_plan
from agent.runtime.tool_planning.visibility import (
    BASELINE_READ_TOOLS,
    LOCAL_OPS_TOOLS,
    _ordered_unique,
    action_class_filter,
    available_canonical_tools,
    build_visibility_metadata,
    governance_filtered_tools,
    scene_allows_local_ops,
)


PLANNER_VERSION = "v2.4"
MAX_CANDIDATE_TOOLS = 12


# ─── Cached lookups ───────────────────────────────────────────────────

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


# ─── ToolPlannerV2 ────────────────────────────────────────────────────


class ToolPlannerV2:
    """Plan tools using SceneDecision and optionally EvidenceBundle."""

    def plan(
        self,
        scene: SceneDecision,
        *,
        evidence_bundle: Any = None,
        available_catalog: dict | None = None,
        model_config: dict | None = None,
    ) -> dict:
        """Produce a validated tool plan.

        Converts SceneDecision → rule_scene via scene_adapter, then
        runs deterministic_plan_tools and validates the output.
        """
        from tool_runtime.tool_namespace import TOOL_NAMESPACE

        rule_scene = scene_to_rule_scene(scene)

        safe_context: dict | None = None
        if evidence_bundle is not None and hasattr(evidence_bundle, "to_safe_context"):
            safe_context = evidence_bundle.to_safe_context()

        if available_catalog is None:
            from agent.runtime.capability_routing.toolset import active_tool_catalog
            available_catalog = active_tool_catalog(
                scene.user_input,
                scene=scene,
                safe_context=safe_context,
                limit=MAX_CANDIDATE_TOOLS,
            )

        plan = deterministic_plan_tools(
            user_input=scene.user_input,
            safe_context=safe_context,
            rule_scene=rule_scene,
            available_catalog=available_catalog,
        )

        # Validate
        available = available_canonical_tools(available_catalog)
        valid, messages = validate_tool_plan(plan, available, user_input=scene.user_input)

        # Evidence-aware adjustments
        self._apply_evidence_adjustments(plan, evidence_bundle, messages)

        # Attach planner metadata
        plan["tool_planner"] = {
            "planner_version": plan.get("planner_version", ""),
            "mode": "deterministic",
            "valid": valid,
            "fallback_used": False,
            "warnings": messages,
        }
        if "capability_routing" in available_catalog:
            plan["capability_routing"] = available_catalog["capability_routing"]
        return plan

    def _apply_evidence_adjustments(
        self,
        plan: dict,
        evidence_bundle: Any,
        messages: list[str],
    ) -> None:
        """Adjust tool plan based on evidence bundle layers and conflicts."""
        if evidence_bundle is None:
            return

        # When conflicts exist, warn about high-risk exec usage
        conflicts = getattr(evidence_bundle, "conflicts", None)
        if conflicts:
            messages.append("evidence_conflicts_detected: use exec tools with caution")
            plan.setdefault("evidence_warnings", []).append(
                "Conflicting evidence detected — verify before executing"
            )

        # Artifact layer presence → ensure file tools visible
        artifact_layer = getattr(evidence_bundle, "artifact_layer", None)
        if artifact_layer and getattr(artifact_layer, "items", None):
            candidates = plan.get("candidate_tools", [])
            file_tools = ["workspace.file.read", "workspace.file.list", "workspace.file.preview"]
            for ft in file_tools:
                if ft not in candidates:
                    candidates.append(ft)
            plan["candidate_tools"] = candidates

        # Knowledge layer presence → note in plan
        knowledge_layer = getattr(evidence_bundle, "knowledge_layer", None)
        if knowledge_layer and getattr(knowledge_layer, "items", None):
            plan.setdefault("evidence_sources", []).append("knowledge")


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

    available = available_canonical_tools(available_catalog)
    seed = deterministic_plan_tools(user_input, safe_context, rule_scene, available_catalog)
    seed_valid, seed_messages = validate_tool_plan(seed, available, user_input=user_input)
    if not seed_valid:
        seed = deterministic_plan_tools(user_input, safe_context, rule_scene, available_catalog)
        seed_valid, seed_messages = validate_tool_plan(seed, available, user_input=user_input)

    plan = seed
    fallback_used = False
    validation_messages = list(seed_messages)

    # Preserve capability routing metadata from the catalog
    if "capability_routing" in available_catalog:
        plan["capability_routing"] = available_catalog["capability_routing"]

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
    available = available_canonical_tools(available_catalog)
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
        tools = governance_filtered_tools(raw_tools, filtered)
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
        tools = governance_filtered_tools(
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
    candidate_tools = action_class_filter(candidate_tools, rule_scene)

    local_ops_enabled = scene_allows_local_ops(rule_scene, user_input)
    baseline_tools = list(BASELINE_READ_TOOLS)
    if local_ops_enabled:
        baseline_tools.extend(LOCAL_OPS_TOOLS)
    else:
        filtered["local_ops_filtered"].extend([tid for tid in LOCAL_OPS_TOOLS if tid in available])

    candidate_tools = _ordered_unique([*candidate_tools, *baseline_tools])
    # When the catalog came from capability routing, trust its tool selection
    if "capability_routing" in available_catalog:
        candidate_tools = _ordered_unique([*candidate_tools, *[tid for tid in available]])
    candidate_tools = governance_filtered_tools([tid for tid in candidate_tools if tid in available], filtered)

    if not local_ops_enabled:
        _local_ops_set = set(LOCAL_OPS_TOOLS)
        _stripped = [t for t in candidate_tools if t in _local_ops_set]
        candidate_tools = [t for t in candidate_tools if t not in _local_ops_set]
        if _stripped:
            filtered.setdefault("local_ops_filtered", [])
            filtered["local_ops_filtered"].extend(_stripped)
            filtered["local_ops_filtered"] = _ordered_unique(filtered["local_ops_filtered"])

    _has_config_tools = {"network.config.parse", "network.config.translate",
                         "network.interface.extract", "network.route.extract"} & set(candidate_tools)
    _has_file_tools = {"workspace.file.read", "workspace.file.preview",
                       "workspace.file.list"} & set(candidate_tools)
    if _has_config_tools and not _has_file_tools:
        candidate_tools = _ordered_unique(["workspace.file.list", "workspace.file.read", *candidate_tools])

    needs_clarification = _needs_file_clarification(user_input, safe_context, rule_scene)

    if needs_clarification and not {"workspace.file.read", "workspace.file.preview"} & set(candidate_tools):
        candidate_tools = _ordered_unique(["workspace.file.list", *candidate_tools])

    categories, groups = categories_groups_from_tools(candidate_tools, rule_scene)
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
    plan["tool_chain"] = tool_chain_from_plan(steps)
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


# ─── Capability steps from rule scene ──────────────────────────────────


def _capability_steps_from_rule_scene(user_input: str, rule_scene: dict) -> list[dict[str, Any]]:
    """Build capability steps from rule_scene signals.

    Uses keyword-driven dispatch via SIGNAL_DISPATCH.
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

    for signal_keys, action_id, goal in SIGNAL_DISPATCH:
        if any(signals.get(k) for k in signal_keys):
            add(action_id, goal)

    lower = (user_input or "").lower()
    if ("translate" in lower or "翻译" in lower) and "network.config.translate" in CAPABILITY_ACTIONS:
        add("network.config.translate", "离线翻译网络配置")

    if not steps:
        for chain_step in rule_scene.get("tool_chain") or []:
            tools = list(chain_step.get("preferred_tools") or [])
            action_id = action_for_tool_set(tools)
            add(action_id, chain_step.get("purpose") or f"执行能力动作 {action_id}")
    return steps


# ─── Helpers ───────────────────────────────────────────────────────────


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


def _finalize_plan(plan: dict, *, mode: str, valid: bool, fallback_used: bool, warnings: list[str]) -> dict:
    out = dict(plan)
    out["planner_version"] = PLANNER_VERSION
    out["mode"] = mode
    out.setdefault("needs_clarification", False)
    out.setdefault("clarifying_question", "")
    out.setdefault("tool_chain", tool_chain_from_plan(out.get("tool_plan") or []))
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
