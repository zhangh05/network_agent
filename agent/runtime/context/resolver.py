# agent/runtime/context/resolver.py
"""ContextResolver — resolves a ContextFrame from a query plan."""

from __future__ import annotations

from typing import Any

from agent.runtime.context.frame import ContextFrame
from agent.runtime.context.query_plan import ContextQueryPlan


class ContextResolver:
    """Resolve context sources into a ContextFrame."""

    def resolve(self, ctx: Any, plan: ContextQueryPlan) -> ContextFrame:
        """Build a ContextFrame by loading sources specified in the plan.

        Args:
            ctx:  TurnContext with workspace_id, session_id, etc.
            plan: ContextQueryPlan describing what to load.

        Returns:
            Populated ContextFrame.
        """
        frame = ContextFrame(
            workspace_id=getattr(ctx, "workspace_id", ""),
            session_id=getattr(ctx, "session_id", ""),
            turn_id=getattr(ctx, "turn_id", ""),
            trace_id=getattr(ctx, "trace_id", ""),
            user_input=getattr(ctx, "user_input", ""),
            scene_decision=getattr(ctx, "scene_decision", None),
        )

        # Load workspace state
        if plan.include_workspace:
            frame.workspace_state = self._load_workspace_state(frame.workspace_id)

        # Load artifacts
        if plan.include_artifacts:
            frame.active_artifacts = self._load_artifacts(frame.workspace_id)

        # Load history
        if plan.include_history:
            frame.recent_history = list(
                (getattr(ctx, "history_window", None) or [])[:plan.history_window]
            )

        # Load previous results
        frame.previous_results = self._load_previous_results(ctx)

        return frame

    def _load_workspace_state(self, workspace_id: str) -> dict:
        try:
            from workspace.manager import get_workspace_state
            ws = get_workspace_state(workspace_id)
            return {k: v for k, v in ws.items()
                    if k not in ("source_config", "deployable_config")
                    and "path" not in k.lower()}
        except Exception:
            return {}

    def _load_artifacts(self, workspace_id: str) -> list:
        try:
            from artifacts.store import list_artifacts
            arts = list_artifacts(workspace_id, limit=10)
            return [
                {
                    "artifact_id": a.get("artifact_id"),
                    "artifact_type": a.get("artifact_type"),
                    "title": a.get("title", ""),
                    "summary": a.get("summary", "")[:200],
                }
                for a in arts
            ]
        except Exception:
            return []

    def _load_previous_results(self, ctx: Any) -> list:
        meta = getattr(ctx, "metadata", {})
        prev = meta.get("previous_results")
        if isinstance(prev, list):
            return prev[:3]
        return []
