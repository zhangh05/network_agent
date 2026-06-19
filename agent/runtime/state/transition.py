# agent/runtime/state/transition.py
"""State transition helpers for task / step lifecycle."""

from __future__ import annotations

from typing import Optional

from agent.runtime.state.models import RuntimeState, TaskState, StepState


class RuntimeStateTransition:
    """Apply signals and results to advance task/step state."""

    def apply_task_signal(self, state: RuntimeState, signal_kind: str, task: Optional[TaskState] = None) -> RuntimeState:
        if signal_kind == "new_task" and task:
            task.status = "running"
            state.active_task = task
            state.tasks.append(task)
            state.session.active_task_id = task.task_id
        elif signal_kind == "cancel_task" and state.active_task:
            state.active_task.status = "failed"
            state.active_task.failure_reason = "cancelled_by_user"
            state.session.last_task_id = state.active_task.task_id
            state.session.active_task_id = None
            state.active_task = None
            state.active_workflow = None
        elif signal_kind == "continue_task":
            pass  # keep running
        return state

    def apply_step_result(self, state: RuntimeState, step_id: str, status: str, summary: str = "", error: str = "") -> RuntimeState:
        wf = state.active_workflow
        if not wf:
            return state

        # Update the step
        for step in wf.steps:
            if step.step_id == step_id:
                step.status = status
                step.result_summary = summary
                step.error = error
                break

        # Advance to next step if current completed
        if status == "completed":
            ordered = sorted(wf.steps, key=lambda s: s.order)
            next_step = None
            found = False
            for s in ordered:
                if found and s.status == "pending":
                    next_step = s
                    break
                if s.step_id == step_id:
                    found = True
            if next_step:
                wf.current_step_id = next_step.step_id
                next_step.status = "running"
                if state.active_task:
                    state.active_task.current_step_id = next_step.step_id
            else:
                # All steps done
                all_completed = all(s.status in ("completed", "skipped") for s in wf.steps)
                if all_completed:
                    wf.status = "completed"
                    if state.active_task:
                        state.active_task.status = "completed"
                        completed_count = sum(1 for s in wf.steps if s.status in ("completed", "skipped"))
                        state.active_task.progress_percent = 100.0

        elif status == "failed":
            wf.status = "failed"
            if state.active_task:
                state.active_task.status = "failed"
                state.active_task.failure_reason = error

        # Update progress
        if wf.steps:
            completed_count = sum(1 for s in wf.steps if s.status in ("completed", "skipped"))
            wf.progress_percent = round(completed_count / len(wf.steps) * 100, 1)
            if state.active_task:
                state.active_task.progress_percent = wf.progress_percent

        return state
