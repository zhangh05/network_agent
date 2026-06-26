# agent/runtime/durable/interrupt.py
"""Phase 4: Interrupt / Approval primitives.

interrupt_before_tool: high-risk tools are NOT directly blocked; they
  create a checkpoint + pending_action, set status=waiting_approval.

resume_after_approval: resolve the interrupt with approve/reject/edit_args.
"""

from __future__ import annotations
from typing import Optional, Literal
from .models import (
    TaskState, RuntimeStep, RuntimeEvent, RuntimeCheckpoint,
    _next_id, _now,
)
from .store import save_task, append_event, save_checkpoint, get_task

Decision = Literal["approve", "reject", "edit_args", "respond_with_feedback"]


def interrupt_before_tool(
    ws_id: str,
    session_id: str,
    run_id: str,
    step: RuntimeStep,
    tool_invocation: dict,
    risk_decision: dict,
) -> dict:
    """Interrupt execution before a high-risk tool.

    Looks up the active task for (ws_id, session_id), creates checkpoint
    and pending_action, sets status=waiting_approval.

    Returns dict with status and approval_id.
    """
    # Find active task
    from .store import list_tasks as _list
    tasks = _list(ws_id, session_id=session_id, limit=5)
    task = None
    for t in tasks:
        if t.status in ("running", "waiting_approval", "interrupting"):
            task = t
            break
    if not task:
        return {"ok": False, "error": "no active task found for session"}

    sid = task.session_id
    rid = task.run_id

    # 1. Build pending_action (redacted)
    pending_action = {
        "action_id": _next_id("act"),
        "type": "tool_call",
        "tool_id": tool_invocation.get("tool_id", ""),
        "step_id": step.step_id,
        "input_args_redacted": _redact_args(tool_invocation.get("arguments", {})),
        "input_args_hash": _hash_args(tool_invocation.get("arguments", {})),
        "risk_level": risk_decision.get("risk_level", "high"),
        "created_at": _now(),
    }

    # 2. Create RuntimeCheckpoint with pending_action
    cp = RuntimeCheckpoint(
        checkpoint_id=_next_id("cp-int"),
        task_id=task.task_id, workspace_id=ws_id,
        session_id=sid, run_id=rid,
        step_id=step.step_id,
        state_snapshot=task.to_dict(),
        pending_action=pending_action,
        artifact_refs=list(task.artifact_ids),
    )
    from .store import save_checkpoint as sc
    sc(cp)

    # 3. Create ApprovalStore request
    approval_id = ""
    try:
        from agent.approval import get_approval_store
        store = get_approval_store()
        store.create(
            session_id=sid,
            tool_id=tool_invocation.get("tool_id", ""),
            arguments=tool_invocation.get("arguments", {}),
            description=risk_decision.get("reason", "High-risk tool requires approval"),
            risk_level=risk_decision.get("risk_level", "high"),
            workspace_id=ws_id,
            run_id=rid,
            job_id=task.job_id,
            metadata={
                "task_id": task.task_id,
                "step_id": step.step_id,
                "pending_action_id": pending_action["action_id"],
            },
        )
        # Get the approval_id from the created record
        pending = store.get_pending(session_id=sid)
        for p in pending:
            if p.get("tool_id") == tool_invocation.get("tool_id"):
                approval_id = p.get("approval_id", "")
                break
    except Exception:
        pass

    # 4. Update TaskState
    task.pending_approval_id = approval_id
    task.pending_action_id = pending_action["action_id"]
    task.interrupted_at = _now()
    task.update_status("waiting_approval")
    step.status = "waiting_approval"  # type: ignore
    save_task(task)

    # 5. Events
    append_event(RuntimeEvent(
        event_id=_next_id("evt-approval"),
        task_id=task.task_id, workspace_id=ws_id,
        session_id=sid, run_id=rid, step_id=step.step_id,
        type="approval_required", status="pending",
        title=f"Approval required: {tool_invocation.get('tool_id', '')}",
        summary=risk_decision.get("reason", ""),
        payload_redacted={"risk_level": risk_decision.get("risk_level", "")},
    ))
    append_event(RuntimeEvent(
        event_id=_next_id("evt-interrupt"),
        task_id=task.task_id, workspace_id=ws_id,
        session_id=sid, run_id=rid, step_id=step.step_id,
        type="task_interrupted", status="interrupting",
        title="Task interrupted for approval",
    ))

    return {
        "ok": True,
        "status": "waiting_approval",
        "approval_id": approval_id,
        "pending_action_id": pending_action["action_id"],
        "checkpoint_id": cp.checkpoint_id,
    }


def resume_after_approval(
    task_id: str, ws_id: str, approval_id: str,
    decision: Decision,
    edited_args: Optional[dict] = None,
    feedback: str = "",
    reason: str = "",
) -> dict:
    """Resume a task after approval decision.

    decision: approve | reject | edit_args | respond_with_feedback
    """
    task = get_task(ws_id, task_id)
    if not task or task.workspace_id != ws_id:
        return {"ok": False, "error": "task not found in workspace"}

    if task.status != "waiting_approval":
        return {"ok": False, "error": f"task status is {task.status}, not waiting_approval"}

    if task.pending_approval_id and task.pending_approval_id != approval_id:
        return {"ok": False, "error": "approval_id mismatch — bound to different pending action"}

    sid = task.session_id
    rid = task.run_id

    if decision == "approve":
        task.update_status("running")
        task.pending_approval_id = None
        task.pending_action_id = ""
        # Mark step ready to execute
        try:
            task.tool_results.append({"__edited_args__": edited_args, "step_id": task.current_step_id})
        except: pass
        for s in task.steps:
            if s.step_id == task.current_step_id and s.status == "waiting_approval":
                s.status = "running"
        save_task(task)

        append_event(RuntimeEvent(
            event_id=_next_id("evt-approved"), task_id=task_id, workspace_id=ws_id,
            session_id=sid, run_id=rid, step_id=task.current_step_id,
            type="approval_approved", status="approved",
            title="Approval granted", summary=reason or "User approved",
        ))
        append_event(RuntimeEvent(
            event_id=_next_id("evt-resume"), task_id=task_id, workspace_id=ws_id,
            session_id=sid, run_id=rid, step_id=task.current_step_id,
            type="task_resumed", status="ok",
            title="Task resumed after approval",
        ))
        return {"ok": True, "status": "running", "decision": "approved"}

    elif decision == "reject":
        task.update_status("failed")
        task.pending_approval_id = None
        task.pending_action_id = ""
        try:
            task.tool_results.append({"__edited_args__": edited_args, "step_id": task.current_step_id})
        except: pass
        for s in task.steps:
            if s.step_id == task.current_step_id:
                s.status = "failed"
                s.summary = f"Rejected: {reason or 'User denied'}"
        task.errors.append(f"approval_rejected: {reason or 'User denied'}")
        save_task(task)

        append_event(RuntimeEvent(
            event_id=_next_id("evt-rejected"), task_id=task_id, workspace_id=ws_id,
            session_id=sid, run_id=rid, step_id=task.current_step_id,
            type="approval_rejected", status="rejected",
            title="Approval rejected", summary=reason or "User denied",
        ))
        return {"ok": True, "status": "failed", "decision": "rejected"}

    elif decision == "edit_args":
        if not edited_args:
            return {"ok": False, "error": "edited_args required for edit_args decision"}

        # Validate schema (basic check)
        if not isinstance(edited_args, dict):
            return {"ok": False, "error": "edited_args must be a dict"}

        task.update_status("running")
        task.pending_approval_id = None
        task.pending_action_id = ""
        try:
            task.tool_results.append({"__edited_args__": edited_args, "step_id": task.current_step_id})
        except: pass
        for s in task.steps:
            if s.step_id == task.current_step_id:
                s.status = "running"
                s.summary = f"Args edited: {str(edited_args)[:100]}"
        save_task(task)

        append_event(RuntimeEvent(
            event_id=_next_id("evt-edited"), task_id=task_id, workspace_id=ws_id,
            session_id=sid, run_id=rid, step_id=task.current_step_id,
            type="approval_args_edited", status="approved",
            title="Args edited and approved",
            payload_redacted={"edited_keys": list(edited_args.keys())},
        ))
        append_event(RuntimeEvent(
            event_id=_next_id("evt-resume"), task_id=task_id, workspace_id=ws_id,
            session_id=sid, run_id=rid, step_id=task.current_step_id,
            type="task_resumed", status="ok",
            title="Task resumed with edited args",
        ))
        return {"ok": True, "status": "running", "decision": "edit_args",
                "edited_args_keys": list(edited_args.keys())}

    elif decision == "respond_with_feedback":
        task.update_status("interrupted")
        task.pending_approval_id = None
        task.pending_action_id = ""
        task.warnings.append(f"feedback: {feedback or reason}")
        save_task(task)

        append_event(RuntimeEvent(
            event_id=_next_id("evt-feedback"), task_id=task_id, workspace_id=ws_id,
            session_id=sid, run_id=rid, step_id=task.current_step_id,
            type="approval_feedback", status="done",
            title="User feedback", summary=feedback or reason,
        ))
        return {"ok": True, "status": "interrupted", "decision": "feedback"}

    return {"ok": False, "error": f"unknown decision: {decision}"}


# ── helpers ──

import hashlib, json

def _redact_args(args: dict) -> dict:
    """Return args with sensitive keys replaced."""
    sensitive = {"password","token","api_key","secret","credential","key","auth"}
    return {k: "[REDACTED]" if k.lower() in sensitive else v for k, v in args.items()}

def _hash_args(args: dict) -> str:
    """SHA256 of canonical JSON args — used to verify integrity."""
    try:
        raw = json.dumps(args, sort_keys=True, ensure_ascii=False).encode()
        return hashlib.sha256(raw).hexdigest()[:16]
    except Exception:
        return ""
