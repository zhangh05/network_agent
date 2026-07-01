# agent/runtime/tool_planning/planner.py
"""ToolPlannerV2 + deterministic planner — canonical planner for the cognition layer.

All core planner logic migrated from agent/runtime/tool_planner.py.
Uses SceneDecision + EvidenceBundle to produce a validated tool plan.
"""

from __future__ import annotations

import os
from functools import lru_cache
from types import SimpleNamespace
from typing import Any

# v3.9.4: the planner resolves tools directly from TOOL_NAMESPACE.
# Business capabilities are descriptive guidance only; they are not a
# dispatch layer, permission layer, or visibility gate.
from tool_runtime.tool_namespace import TOOL_NAMESPACE, ALL_TOOL_IDS, get_namespace_entry


def tools_for_action(action_id: str, *, available=None, **_) -> list[str]:
    """v3.9.3 inline: 1:1 mapping. Returns [action_id] when known canonical id."""
    if action_id in TOOL_NAMESPACE:
        if available is None or action_id in available:
            return [action_id]
    return []


def action_for_tool_set(tool_ids: list[str]) -> str:
    """v3.9.3 inline: pick the first tool id as the representative action."""
    return tool_ids[0] if tool_ids else ""

from agent.runtime.cognition.scene_decision import SceneDecision
from agent.runtime.tool_planning.chain_builder import (
    SIGNAL_DISPATCH,
    categories_groups_from_tools,
    tool_chain_from_plan,
)
from agent.runtime.tool_planning.scene_adapter import scene_to_rule_scene
from agent.runtime.tool_planning.validation import validate_tool_plan


def _ordered_unique(items) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


PLANNER_VERSION = "v2.4"
MAX_CANDIDATE_TOOLS = 30  # 17 baseline + routing + overhead


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
        return _noop_governance_entry(tool_id)
    except Exception:
        return SimpleNamespace(status="unknown")


def _noop_governance_entry(tool_id: str):
    """v3.9.3: tool_governance was removed; namespace membership is the gate."""
    return SimpleNamespace(status="active" if tool_id in TOOL_NAMESPACE else "unknown")


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
            # v3.9.4: all canonical tools are known to the planner;
            # scene signals choose the turn-visible subset.
            available_catalog = {
                "tools": list(TOOL_NAMESPACE),
                "business_capabilities": [],
            }

        plan = deterministic_plan_tools(
            user_input=scene.user_input,
            safe_context=safe_context,
            rule_scene=rule_scene,
            available_catalog=available_catalog,
        )

        # Validate
        available = set(ALL_TOOL_IDS)
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
        # ── Build ToolPlanningDecision (hard contract for audit/inspection) ──
        from agent.runtime.tool_planning.decision import ToolPlanningDecision
        from agent.runtime.tool_planning.policy import ToolPlanningPolicy

        policy = ToolPlanningPolicy.default()
        decision = ToolPlanningDecision.from_plan(
            plan,
            business_capabilities=available_catalog.get("business_capabilities"),
            policy=policy,
        )
        plan["tool_planning_decision"] = decision.to_dict()

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
            # v3.9.1.1: merged workspace.file (action=list|read|read_image|edit|patch|write_artifact)
            for ft in ["workspace.file"]:
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

    available = set(ALL_TOOL_IDS)
    seed = deterministic_plan_tools(user_input, safe_context, rule_scene, available_catalog)
    seed_valid, seed_messages = validate_tool_plan(seed, available, user_input=user_input)
    if not seed_valid:
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
    """Build a deterministic plan with ALL tools visible (v3.9.6).

    No scene gating, no action_class filtering, no governance layer.
    The capability_steps are kept for audit / tool_plan display but
    do not restrict the candidate set.
    """
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
        raw_tools = [action_id] if action_id in TOOL_NAMESPACE else []
        tools = [t for t in raw_tools if t in TOOL_NAMESPACE]
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
        raw = list(rule_scene.get("candidate_tools", []))[:5]
        tools = [t for t in raw if t in TOOL_NAMESPACE]
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

    # All tools are always in the candidate set
    candidate_tools = _ordered_unique(list(ALL_TOOL_IDS))

    categories, groups = categories_groups_from_tools(candidate_tools, rule_scene)
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
        "visibility": {
            "scene": primary,
            "reason": rule_scene.get("reason", ""),
            "candidate_count": len(candidate_tools),
            "local_ops_enabled": True,   # all canonical tools are available
            "visible_tools": list(candidate_tools),
            "filtered": {},
        },
        "needs_clarification": False,
        "clarifying_question": "",
        "reason": rule_scene.get("reason", "deterministic planner: all tools visible (v3.9.6)"),
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
    """Optional LLM planner — refines the deterministic seed plan.

    v3.3: Enabled. Lightweight refinement: uses LLM to adjust candidate tools
    and reorder capability steps based on conversation nuance that deterministic
    keyword matching cannot capture.
    """
    if not model_config or not model_config.get("enabled"):
        return None

    try:
        from agent.llm.runtime import get_runtime
        runtime = get_runtime()
        if not runtime:
            return None

        available = set(ALL_TOOL_IDS)
        seed_tools = seed_plan.get("candidate_tools", [])
        seed_steps = seed_plan.get("tool_plan", [])

        # Build a compact prompt for LLM refinement
        tool_list = "\n".join(
            f"- {tid}" for tid in (seed_tools[:20] or available[:20])
        )
        steps_desc = "\n".join(
            f"  Step {s.get('step','?')}: {s.get('goal','?')} → tools:{s.get('tool_candidates',[])[:3]}"
            for s in seed_steps[:5]
        )

        prompt = (
            f"Refine this tool plan for the user request.\n"
            f"User: {user_input[:300]}\n\n"
            f"Available tools:\n{tool_list}\n\n"
            f"Current plan:\n{steps_desc}\n\n"
            f"Return a JSON with keys: 'candidate_tools' (list of tool IDs, no more than 15), "
            f"and optionally 'reorder_steps' (list of step numbers). "
            f"Only add tools that are in the available list. Only respond with valid JSON."
        )

        resp = runtime.chat(prompt, temperature=0.3, max_tokens=512)
        if not resp:
            return None

        import json as _json
        content = resp.content if hasattr(resp, "content") else str(resp)
        # Extract JSON from response
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[-1].rsplit("\n```", 1)[0]
        try:
            refined = _json.loads(content)
        except _json.JSONDecodeError:
            return None

        if not isinstance(refined, dict):
            return None

        new_tools = refined.get("candidate_tools", [])
        if not isinstance(new_tools, list) or not new_tools:
            return None

        # Validate: only keep tools that are in available
        valid_tools = [tid for tid in new_tools if isinstance(tid, str) and tid in available]
        if not valid_tools:
            return None

        # Build refined plan
        refined_plan = dict(seed_plan)
        refined_plan["candidate_tools"] = _ordered_unique([*valid_tools, *seed_tools])[:MAX_CANDIDATE_TOOLS]

        # Update capability steps if reorder requested
        reorder = refined.get("reorder_steps", [])
        if isinstance(reorder, list) and len(reorder) == len(seed_steps):
            new_steps = [seed_steps[i - 1] for i in reorder if 1 <= i <= len(seed_steps)]
            if len(new_steps) == len(seed_steps):
                for j, s in enumerate(new_steps):
                    s = dict(s)
                    s["step"] = j + 1
                    new_steps[j] = s
                refined_plan["tool_plan"] = new_steps

        refined_plan["tool_planner"] = {
            "planner_version": PLANNER_VERSION,
            "mode": "llm_refined",
            "valid": True,
            "fallback_used": False,
            "warnings": [],
        }
        return refined_plan

    except Exception:
        return None


# ─── Capability steps from rule scene ──────────────────────────────────


def _capability_steps_from_rule_scene(user_input: str, rule_scene: dict) -> list[dict[str, Any]]:
    """Build canonical tool steps from rule_scene signals.

    Uses keyword-driven dispatch via SIGNAL_DISPATCH.
    """
    signals = rule_scene.get("signals") or {}
    steps: list[dict[str, Any]] = []
    seen_actions: set[str] = set()

    def add(action_id: str, goal: str) -> None:
        if action_id in TOOL_NAMESPACE and action_id not in seen_actions:
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
    if ("translate" in lower or "翻译" in lower) and "config.manage" in TOOL_NAMESPACE:
        add("config.manage", "离线翻译网络配置")

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
    if "config.manage" in tools or "pcap.manage" in tools:  # v3.9.2
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
