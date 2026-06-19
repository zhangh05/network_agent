# agent/runtime/tasking/completion.py
"""Evaluate whether a task has reached completion."""

from __future__ import annotations

from typing import Optional

from agent.runtime.state.models import RuntimeState, TaskState


class CompletionEvaluator:
    """Check workflow state to decide if the task is complete."""

    def evaluate(self, ctx, state: RuntimeState) -> Optional[TaskState]:
        """Return the TaskState with updated status if task is complete, else None."""
        task = state.active_task
        wf = state.active_workflow

        if not task or not wf:
            return None

        if not wf.steps:
            return None

        all_done = all(s.status in ("completed", "skipped") for s in wf.steps)
        any_failed = any(s.status == "failed" for s in wf.steps)

        if any_failed:
            task.status = "failed"
            failed_steps = [s for s in wf.steps if s.status == "failed"]
            task.failure_reason = "; ".join(s.error or s.title for s in failed_steps)
            wf.status = "failed"
            return task

        if all_done:
            task.status = "completed"
            task.progress_percent = 100.0
            task.result_summary = "; ".join(
                s.result_summary for s in wf.steps if s.result_summary
            )
            wf.status = "completed"
            wf.progress_percent = 100.0
            state.session.last_task_id = task.task_id
            state.session.active_task_id = None
            return task

        return None
