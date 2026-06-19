# agent/runtime/tasking/progress.py
"""Calculate task progress from workflow state."""

from __future__ import annotations

from agent.runtime.state.models import RuntimeState
from agent.runtime.tasking.models import TaskProgress


class TaskProgressCalculator:
    """Compute progress from the active workflow's step states."""

    def calculate(self, state: RuntimeState) -> TaskProgress:
        task = state.active_task
        wf = state.active_workflow

        if not task:
            return TaskProgress()

        if not wf or not wf.steps:
            return TaskProgress(
                task_id=task.task_id,
                status=task.status,
            )

        completed = sum(1 for s in wf.steps if s.status in ("completed", "skipped"))
        total = len(wf.steps)
        pct = round(completed / total * 100, 1) if total else 0.0

        return TaskProgress(
            task_id=task.task_id,
            current_step_id=wf.current_step_id,
            completed_steps=completed,
            total_steps=total,
            progress_percent=pct,
            status=task.status,
        )
