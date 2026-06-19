# agent/runtime/state/resolver.py
"""Resolve full RuntimeState from TurnContext."""

from __future__ import annotations

from agent.runtime.state.models import (
    RuntimeState, SessionState, WorkspaceState, ActionState,
)
from agent.runtime.state.store import RuntimeStateStore


class RuntimeStateResolver:
    """Build a RuntimeState from ctx, fill session/workspace/action info."""

    def __init__(self, store: RuntimeStateStore | None = None):
        self._store = store or RuntimeStateStore()

    def resolve(self, ctx) -> RuntimeState:
        state = self._store.load(ctx)

        # Fill session info from ctx
        state.session.session_id = getattr(ctx, "session_id", "") or state.session.session_id
        state.session.turn_count += 1

        # Fill workspace info
        state.workspace.workspace_id = getattr(ctx, "workspace_id", "") or state.workspace.workspace_id

        # Ingest action_trace from ctx.metadata (written by ActionAuditTrail)
        action_trace = ctx.metadata.get("action_trace", [])
        for entry in action_trace:
            if isinstance(entry, dict):
                aid = entry.get("action_id", "")
                if aid and not any(a.action_id == aid for a in state.actions):
                    state.actions.append(ActionState(
                        action_id=aid,
                        task_id=state.active_task.task_id if state.active_task else "",
                        tool_id=entry.get("tool_id", ""),
                        action_class=entry.get("action_class", "unknown"),
                        risk_level=entry.get("risk_level", "low"),
                        status=entry.get("status", "success"),
                        summary=entry.get("summary", ""),
                    ))

        # Pending approvals
        pending = ctx.metadata.get("pending_approvals", [])
        if pending and state.active_task:
            state.active_task.status = "approval_pending"

        # Set ctx.runtime_state
        ctx.runtime_state = state
        return state
