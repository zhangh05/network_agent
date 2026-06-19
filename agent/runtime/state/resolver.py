# agent/runtime/state/resolver.py
"""Resolve full RuntimeState from TurnContext."""

from __future__ import annotations

from agent.runtime.state.models import RuntimeState, ActionState
from agent.runtime.state.store import RuntimeStateStore


class RuntimeStateResolver:
    """Build a RuntimeState from ctx and fill session/workspace/action info."""

    def __init__(self, store: RuntimeStateStore | None = None):
        self._store = store or RuntimeStateStore()

    def resolve(self, ctx) -> RuntimeState:
        state = self._store.load(ctx)

        state.session.session_id = getattr(ctx, "session_id", "") or state.session.session_id
        state.session.turn_count += 1
        state.workspace.workspace_id = getattr(ctx, "workspace_id", "") or state.workspace.workspace_id

        action_trace = ctx.metadata.get("action_trace", [])
        existing_ids = {a.action_id for a in state.actions}
        for entry in action_trace:
            if not isinstance(entry, dict):
                continue
            action_id = entry.get("action_id", "")
            if not action_id or action_id in existing_ids:
                continue
            state.actions.append(ActionState(
                action_id=action_id,
                task_id=state.active_task.task_id if state.active_task else "",
                step_id=(state.active_workflow.current_step_id if state.active_workflow else ""),
                tool_id=entry.get("tool_id", ""),
                action_class=entry.get("action_class", "unknown"),
                risk_level=entry.get("risk_level", "low"),
                status=entry.get("status", "success"),
                summary=entry.get("summary", ""),
            ))
            existing_ids.add(action_id)

        if ctx.metadata.get("pending_approvals") and state.active_task:
            state.active_task.status = "approval_pending"

        ctx.runtime_state = state
        ctx.metadata["runtime_state_summary"] = _summary(state, ctx)
        return state


def _summary(state: RuntimeState, ctx) -> str:
    task = state.active_task
    workflow = state.active_workflow
    active_task = task.task_id if task else "none"
    task_status = task.status if task else "none"
    current_step = workflow.current_step_id if workflow else "none"
    progress = task.progress_percent if task else 0
    approvals = len(ctx.metadata.get("pending_approvals", []) or [])
    return (
        f"active_task={active_task} status={task_status} "
        f"current_step={current_step} progress={progress} "
        f"pending_approvals={approvals}"
    )[:1500]
