# agent/runtime/context/query_plan.py
"""ContextQueryPlan and ContextQueryPlanner."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ContextQueryPlan:
    """Describes what context to fetch for this turn."""

    include_workspace: bool = True
    include_artifacts: bool = False
    include_jobs: bool = False
    include_reports: bool = False
    include_history: bool = True
    history_window: int = 5
    reason: str = ""


class ContextQueryPlanner:
    """Plan context retrieval based on scene decision."""

    def plan(self, scene_decision: Any, ctx: Any = None) -> ContextQueryPlan:
        """Produce a ContextQueryPlan from the scene decision.

        Simple chat = minimal (no workspace/artifacts/jobs).
        File task = include artifacts + workspace.
        """
        if scene_decision is None:
            return ContextQueryPlan(reason="no scene_decision, defaults")

        is_simple = getattr(scene_decision, "is_simple_chat", False)

        if is_simple:
            return ContextQueryPlan(
                include_workspace=False,
                include_artifacts=False,
                include_jobs=False,
                include_reports=False,
                include_history=True,
                history_window=3,
                reason="simple_chat: minimal context",
            )

        is_file = getattr(scene_decision, "is_file_task", False)
        is_network = getattr(scene_decision, "is_network_task", False)
        is_report = getattr(scene_decision, "is_report_task", False)

        return ContextQueryPlan(
            include_workspace=True,
            include_artifacts=is_file or is_network or is_report,
            include_jobs=is_network or is_report,
            include_reports=is_report,
            include_history=True,
            history_window=5,
            reason="task context: workspace + relevant sources",
        )
