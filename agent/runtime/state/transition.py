# agent/runtime/state/transition.py
"""State transition helpers for task and step lifecycle."""

from __future__ import annotations

from agent.runtime.state.models import RuntimeState, TaskState, StepState, WorkflowState
from agent.runtime.tasking.models import TaskPlan, WorkflowPlan, StepResult, TaskSignal


class RuntimeStateTransition:
    """Apply signals, plans, and step results to runtime state."""

    def apply_task_plan(self, state: RuntimeState, task_plan: TaskPlan, workflow_plan: WorkflowPlan, ctx=None) -> RuntimeState:
        task = TaskState(
            task_id=task_plan.task_id,
            title=task_plan.title,
            user_goal=task_plan.user_goal,
            status="running",
            workflow_id=workflow_plan.workflow_id,
            completion_criteria=task_plan.completion_criteria,
            created_turn_id=getattr(ctx, "turn_id", "") if ctx is not None else "",
            updated_turn_id=getattr(ctx, "turn_id", "") if ctx is not None else "",
        )
        steps = []
        for step_plan in workflow_plan.steps:
            steps.append(StepState(
                step_id=step_plan.step_id,
                task_id=task.task_id,
                title=step_plan.title,
                goal=step_plan.goal,
                order=step_plan.order,
                required_evidence=list(step_plan.required_evidence),
                required_actions=list(step_plan.required_actions),
                completion_check=step_plan.completion_check,
            ))
        workflow = WorkflowState(
            workflow_id=workflow_plan.workflow_id,
            task_id=task.task_id,
            status="running",
            steps=steps,
        )
        if workflow.steps:
            first_step = sorted(workflow.steps, key=lambda s: s.order)[0]
            first_step.status = "running"
            workflow.current_step_id = first_step.step_id
            task.current_step_id = first_step.step_id

        state.active_task = task
        state.active_workflow = workflow
        state.tasks = [t for t in state.tasks if t.task_id != task.task_id] + [task]
        state.workflows = [w for w in state.workflows if w.workflow_id != workflow.workflow_id] + [workflow]
        state.session.active_task_id = task.task_id
        if ctx is not None:
            ctx.metadata["task_plan"] = {
                "task_id": task_plan.task_id,
                "title": task_plan.title,
                "steps": list(task_plan.steps),
                "completion_criteria": task_plan.completion_criteria,
            }
            ctx.metadata["workflow_plan"] = {
                "workflow_id": workflow_plan.workflow_id,
                "task_id": workflow_plan.task_id,
                "steps": [s.step_id for s in workflow_plan.steps],
            }
        return state

    def apply_continue(self, state: RuntimeState, signal: TaskSignal, ctx=None) -> RuntimeState:
        if not state.active_task:
            if ctx is not None:
                ctx.metadata.setdefault("runtime_state_warnings", []).append("no_active_task")
            return state
        state.active_task.status = "running"
        workflow = state.active_workflow
        if workflow:
            workflow.status = "running"
            if not workflow.current_step_id:
                for step in sorted(workflow.steps, key=lambda s: s.order):
                    if step.status in ("pending", "running"):
                        workflow.current_step_id = step.step_id
                        state.active_task.current_step_id = step.step_id
                        step.status = "running"
                        break
        state.session.active_task_id = state.active_task.task_id
        return state

    def apply_cancel(self, state: RuntimeState, signal: TaskSignal, ctx=None) -> RuntimeState:
        if not state.active_task:
            if ctx is not None:
                ctx.metadata.setdefault("runtime_state_warnings", []).append("no_active_task_to_cancel")
            return state
        state.active_task.status = "paused"
        state.active_task.failure_reason = "cancelled_by_user"
        if state.active_workflow:
            state.active_workflow.status = "paused"
        state.session.last_task_id = state.active_task.task_id
        state.session.active_task_id = None
        return state

    def apply_task_signal(self, state: RuntimeState, signal_kind: str, task=None) -> RuntimeState:
        if signal_kind == "new_task" and task:
            task.status = "running"
            state.active_task = task
            state.tasks.append(task)
            state.session.active_task_id = task.task_id
        elif signal_kind == "cancel_task" and state.active_task:
            state.active_task.status = "paused"
            state.active_task.failure_reason = "cancelled_by_user"
            state.session.last_task_id = state.active_task.task_id
            state.session.active_task_id = None
        return state

    def apply_step_result(self, state: RuntimeState, step_result: StepResult, ctx=None) -> RuntimeState:
        workflow = state.active_workflow
        if not workflow:
            return state
        step_id = step_result.step_id
        status = step_result.status

        for step in workflow.steps:
            if step.step_id == step_id:
                step.status = status
                step.result_summary = step_result.summary
                step.error = step_result.error
                for action_id in step_result.action_ids:
                    if action_id not in step.action_ids:
                        step.action_ids.append(action_id)
                for artifact_id in step_result.artifact_ids:
                    if artifact_id not in step.artifact_ids:
                        step.artifact_ids.append(artifact_id)
                break

        if status == "completed":
            self._advance_after_completed(state, workflow, step_id)
        elif status == "approval_pending":
            workflow.status = "blocked"
            if state.active_task:
                state.active_task.status = "approval_pending"
        elif status == "blocked":
            workflow.status = "blocked"
            if state.active_task:
                state.active_task.status = "blocked"
        elif status == "failed":
            workflow.status = "failed"
            if state.active_task:
                state.active_task.status = "failed"
                state.active_task.failure_reason = step_result.error

        self._update_progress(state, workflow)
        return state

    def _advance_after_completed(self, state: RuntimeState, workflow: WorkflowState, step_id: str) -> None:
        ordered = sorted(workflow.steps, key=lambda s: s.order)
        next_step = None
        found = False
        for step in ordered:
            if found and step.status == "pending":
                next_step = step
                break
            if step.step_id == step_id:
                found = True
        if next_step:
            workflow.current_step_id = next_step.step_id
            next_step.status = "running"
            if state.active_task:
                state.active_task.current_step_id = next_step.step_id
        else:
            all_done = all(s.status in ("completed", "skipped") for s in workflow.steps)
            if all_done:
                workflow.status = "completed"
                if state.active_task:
                    state.active_task.status = "completed"
                    state.active_task.progress_percent = 100.0

    @staticmethod
    def _update_progress(state: RuntimeState, workflow: WorkflowState) -> None:
        if not workflow.steps:
            return
        completed_count = sum(1 for s in workflow.steps if s.status in ("completed", "skipped"))
        workflow.progress_percent = round(completed_count / len(workflow.steps) * 100, 1)
        if state.active_task:
            state.active_task.progress_percent = workflow.progress_percent
