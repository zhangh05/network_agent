# agent/runtime/state/snapshot.py
"""Create a lightweight RuntimeStateSnapshot for prompt injection / logging."""

from __future__ import annotations

from agent.runtime.state.models import RuntimeState, RuntimeStateSnapshot


class RuntimeStateSnapshotter:
    """Produce a snapshot and write it to ctx.metadata."""

    def snapshot(self, ctx, state: RuntimeState) -> RuntimeStateSnapshot:
        snap = RuntimeStateSnapshot(
            turn_id=getattr(ctx, "turn_id", ""),
            session_id=state.session.session_id,
            workspace_id=state.workspace.workspace_id,
            active_task_id=state.active_task.task_id if state.active_task else None,
            active_step_id=(
                state.active_workflow.current_step_id
                if state.active_workflow else None
            ),
            task_status=state.active_task.status if state.active_task else "",
            workflow_status=state.active_workflow.status if state.active_workflow else "",
            progress_percent=state.active_task.progress_percent if state.active_task else 0.0,
            pending_approvals=ctx.metadata.get("pending_approvals", []),
            recent_actions=[a.action_id for a in state.actions[-5:]],
            recent_artifacts=[a.artifact_id for a in state.artifacts[-5:]],
            warnings=[],
        )
        ctx.metadata["runtime_state_snapshot"] = {
            "turn_id": snap.turn_id,
            "active_task_id": snap.active_task_id,
            "task_status": snap.task_status,
            "progress_percent": snap.progress_percent,
        }
        return snap
