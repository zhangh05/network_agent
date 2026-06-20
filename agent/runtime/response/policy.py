# agent/runtime/response/policy.py
"""ResponsePolicy — determines response_type from runtime state."""

from __future__ import annotations

from agent.runtime.response.models import ResponsePlan


class ResponsePolicy:
    """Determine response_type based on current runtime state and metadata."""

    def decide(self, ctx) -> ResponsePlan:
        snap = ctx.metadata.get("runtime_state_snapshot") or {}
        output_summary = ctx.metadata.get("output_summary") or {}
        pending = ctx.metadata.get("pending_approvals") or snap.get("pending_approvals") or []
        task_status = snap.get("task_status", "")
        artifact_records = ctx.metadata.get("artifact_records") or []
        artifact_ids = [r.get("artifact_id", "") for r in artifact_records if isinstance(r, dict)]
        task_id = snap.get("active_task_id", "")
        step_id = snap.get("active_step_id", "")

        plan = ResponsePlan(task_id=task_id, step_id=step_id)

        if pending:
            plan.response_type = "approval"
            plan.pending_approvals = list(pending)
            plan.status = "awaiting_approval"
        elif task_status == "blocked":
            plan.response_type = "blocked"
            plan.status = "blocked"
        elif task_status == "failed":
            plan.response_type = "failed"
            plan.status = "failed"
        elif artifact_records:
            plan.response_type = "artifact"
            plan.artifact_ids = artifact_ids
            plan.status = "artifacts_ready"
        elif task_status in ("running", "in_progress"):
            plan.response_type = "progress"
            plan.status = "in_progress"
        else:
            plan.response_type = "answer"
            plan.status = "complete"

        plan.warnings = list(output_summary.get("warnings") or [])
        return plan
