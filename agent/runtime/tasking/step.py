# agent/runtime/tasking/step.py
"""Step execution: prepare current step and apply action results."""

from __future__ import annotations

from typing import Optional

from agent.runtime.state.models import RuntimeState, StepState
from agent.runtime.tasking.models import StepResult


class StepExecutor:
    """Manages step-level execution by consuming ActionExecutor results."""

    def prepare_current_step(self, ctx, state: RuntimeState) -> Optional[StepState]:
        """Mark the current step as running, write metadata, and return it."""
        workflow = state.active_workflow
        if not workflow:
            return None
        if not workflow.current_step_id:
            for candidate in sorted(workflow.steps, key=lambda s: s.order):
                if candidate.status in ("pending", "running"):
                    workflow.current_step_id = candidate.step_id
                    break
        if not workflow.current_step_id:
            return None

        for step in workflow.steps:
            if step.step_id == workflow.current_step_id:
                if step.status == "pending":
                    step.status = "running"
                if state.active_task:
                    state.active_task.current_step_id = step.step_id
                ctx.metadata["current_step"] = {
                    "step_id": step.step_id,
                    "task_id": step.task_id,
                    "title": step.title,
                    "goal": step.goal,
                    "status": step.status,
                    "order": step.order,
                }
                return step
        return None

    def apply_action_results(self, ctx, state: RuntimeState) -> Optional[StepResult]:
        """Read current-turn action metadata and produce a StepResult."""
        workflow = state.active_workflow
        if not workflow or not workflow.current_step_id:
            return None

        current_step = None
        for step in workflow.steps:
            if step.step_id == workflow.current_step_id:
                current_step = step
                break
        if not current_step:
            return None

        action_trace = ctx.metadata.get("action_trace", [])
        evidence_updates = ctx.metadata.get("action_evidence_updates", [])
        pending_approvals = ctx.metadata.get("pending_approvals", [])

        action_ids = []
        artifact_ids = []
        has_failed = False
        has_blocked = False
        has_approval_pending = bool(pending_approvals)
        has_success = False
        summaries = []

        seen = set(current_step.action_ids)
        for entry in action_trace:
            if not isinstance(entry, dict) or entry.get("type") != "result":
                continue
            action_id = entry.get("action_id", "")
            if action_id and action_id not in seen:
                action_ids.append(action_id)
                current_step.action_ids.append(action_id)
                seen.add(action_id)
            status = entry.get("status", "")
            ok = bool(entry.get("ok"))
            if status == "approval_pending":
                has_approval_pending = True
            elif status == "blocked":
                has_blocked = True
            elif status == "failed":
                has_failed = True
            elif ok or status == "success":
                has_success = True
            if entry.get("summary"):
                summaries.append(str(entry["summary"]))

        for ev in evidence_updates:
            if not isinstance(ev, dict):
                continue
            artifact_id = ev.get("artifact_id")
            if artifact_id and artifact_id not in current_step.artifact_ids:
                artifact_ids.append(artifact_id)
                current_step.artifact_ids.append(artifact_id)
            if ev.get("summary"):
                summaries.append(str(ev["summary"]))

        if not action_ids and not pending_approvals and not evidence_updates:
            return None

        if has_approval_pending:
            step_status = "approval_pending"
        elif has_blocked:
            step_status = "blocked"
        elif has_failed:
            step_status = "failed"
        elif has_success or evidence_updates:
            step_status = "completed"
        else:
            step_status = "running"

        current_step.status = step_status
        current_step.result_summary = "; ".join(summaries)[:500] if summaries else ""

        return StepResult(
            step_id=current_step.step_id,
            task_id=current_step.task_id,
            status=step_status,
            summary=current_step.result_summary,
            action_ids=action_ids,
            artifact_ids=artifact_ids,
            error=current_step.error,
        )
