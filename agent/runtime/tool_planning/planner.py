# agent/runtime/tool_planning/planner.py
"""ToolPlannerV2 — canonical planner entry point for the refactored cognition layer.

Uses SceneDecision + EvidenceBundle to produce a validated tool plan.
Calls deterministic_plan_tools directly (not the plan_tools wrapper),
then validates via validation.py.
"""

from __future__ import annotations

from typing import Any

from agent.runtime.cognition.scene_decision import SceneDecision
from agent.runtime.tool_planning.scene_adapter import scene_to_rule_scene
from agent.runtime.tool_planning.validation import validate_tool_plan


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
        from agent.runtime.tool_planner import deterministic_plan_tools
        from tool_runtime.tool_namespace import TOOL_NAMESPACE

        rule_scene = scene_to_rule_scene(scene)

        safe_context: dict | None = None
        if evidence_bundle is not None and hasattr(evidence_bundle, "to_safe_context"):
            safe_context = evidence_bundle.to_safe_context()

        if available_catalog is None:
            available_catalog = {"tools": list(TOOL_NAMESPACE)}

        plan = deterministic_plan_tools(
            user_input=scene.user_input,
            safe_context=safe_context,
            rule_scene=rule_scene,
            available_catalog=available_catalog,
        )

        # Validate
        available = _available_canonical_tools(available_catalog)
        valid, messages = validate_tool_plan(plan, available, user_input=scene.user_input)

        # Attach planner metadata
        plan["tool_planner"] = {
            "planner_version": plan.get("planner_version", ""),
            "mode": "deterministic",
            "valid": valid,
            "fallback_used": False,
            "warnings": messages,
        }
        return plan


def _available_canonical_tools(available_catalog: dict) -> set[str]:
    """Compute the set of available canonical tool IDs."""
    from tool_runtime.tool_namespace import TOOL_NAMESPACE
    tools = available_catalog.get("tools") if isinstance(available_catalog, dict) else None
    if tools:
        return {str(t) for t in tools if str(t) in TOOL_NAMESPACE}
    return set(TOOL_NAMESPACE)
