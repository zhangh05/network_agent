# agent/runtime/tasking/step.py
"""Step execution: prepare current step and apply action results."""

from __future__ import annotations

from typing import Optional

from agent.runtime.state.models import RuntimeState, StepState, ActionState, ArtifactState
from agent.runtime.tasking.models import StepResult


class StepExecutor:
    """Manages step-level execution by delegating to ActionExecutor results."""

    def prepare_current_step(self, ctx, state: RuntimeState) -> Optional[StepState]:
        """Mark the current step as running and return it."""
        wf = state.active_workflow
        if not wf or not wf.current_step_id:
            return None

        for step in wf.steps:
            if step.step_id == wf.current_step_id:
                step.status = "running"
                return step
        return None

    def apply_action_results(self, ctx, state: RuntimeState) -> Optional[StepResult]:
        """Read action_trace from ctx.metadata and produce a StepResult."""
        wf = state.active_workflow
        if not wf or not wf.current_step_id:
            return None

        current_step = None
        for step in wf.steps:
            if step.step_id == wf.current_step_id:
                current_step = step
                break
        if not current_step:
            return None

        action_trace = ctx.metadata.get("action_trace", [])
        evidence_updates = ctx.metadata.get("action_evidence_updates", [])

        action_ids = []
        artifact_ids = []
        has_failure = False
        has_approval_pending = False
        summaries = []

        for entry in action_trace:
            if not isinstance(entry, dict):
                continue
            aid = entry.get("action_id", "")
            if aid:
                action_ids.append(aid)
                current_step.action_ids.append(aid)
            status = entry.get("status", "")
            if status == "failed":
                has_failure = True
            if status == "approval_pending":
                has_approval_pending = True
            if entry.get("summary"):
                summaries.append(entry["summary"])

        # Collect artifacts from evidence updates
        for ev in evidence_updates:
            if isinstance(ev, dict) and ev.get("artifact_id"):
                artifact_ids.append(ev["artifact_id"])
                current_step.artifact_ids.append(ev["artifact_id"])

        if has_approval_pending:
            step_status = "approval_pending"
        elif has_failure:
            step_status = "failed"
        else:
            step_status = "completed"

        current_step.status = step_status
        current_step.result_summary = "; ".join(summaries) if summaries else ""

        return StepResult(
            step_id=current_step.step_id,
            task_id=current_step.task_id,
            status=step_status,
            summary=current_step.result_summary,
            action_ids=action_ids,
            artifact_ids=artifact_ids,
            error=current_step.error,
        )
