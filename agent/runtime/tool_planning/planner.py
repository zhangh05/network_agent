# agent/runtime/tool_planning/planner.py
"""ToolPlannerV2 — wraps deterministic_plan_tools with SceneDecision + EvidenceBundle.

The canonical planner entry point for the refactored cognition layer.
"""

from __future__ import annotations

from typing import Any

from agent.runtime.cognition.scene_decision import SceneDecision
from agent.runtime.tool_planning.scene_adapter import scene_to_rule_scene


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

        Converts SceneDecision → rule_scene dict, then delegates to the
        existing plan_tools pipeline for backward-compatible output.
        """
        from agent.runtime.tool_planner import plan_tools

        rule_scene = scene_to_rule_scene(scene)
        safe_context = {}
        if evidence_bundle is not None and hasattr(evidence_bundle, "to_safe_context"):
            safe_context = evidence_bundle.to_safe_context()

        if available_catalog is None:
            from tool_runtime.tool_namespace import TOOL_NAMESPACE
            available_catalog = {"tools": list(TOOL_NAMESPACE)}

        return plan_tools(
            user_input=scene.user_input,
            safe_context=safe_context,
            rule_scene=rule_scene,
            available_catalog=available_catalog,
            model_config=model_config,
        )
