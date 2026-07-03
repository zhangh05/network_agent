"""Tracking policy for CMDB inspection tasks.

Tracking is not retry. Retry repeats a failed tool call; tracking observes a
background task that is already running. This module keeps that distinction
explicit so the LLM and frontend can report the true state without inventing
"retry succeeded" stories.
"""

from __future__ import annotations

from typing import Any

from agent.runtime.utils import now_iso, from_iso

from .models import InspectionTask


TERMINAL_STATUSES = {"succeeded", "partial", "failed", "cancelled", "skipped", "crashed"}


def build_tracking_policy(task: InspectionTask) -> dict[str, Any]:
    total = int(getattr(task, "total_assets", 0) or 0)
    if total <= 1:
        mode = "short"
        deadline_seconds = 300
        poll_seconds = 5
        max_polls = 30
        max_same_status = 12
    elif total <= 10:
        mode = "medium"
        deadline_seconds = 1800
        poll_seconds = 10
        max_polls = 90
        max_same_status = 18
    else:
        mode = "long_inspection"
        deadline_seconds = 3600
        poll_seconds = 30
        max_polls = 120
        max_same_status = 20
    return {
        "mode": mode,
        "deadline_seconds": deadline_seconds,
        "poll_seconds": poll_seconds,
        "max_polls": max_polls,
        "max_same_status": max_same_status,
        "terminal_statuses": sorted(TERMINAL_STATUSES),
    }


def ensure_tracking(task: InspectionTask, *, source: str = "inspection") -> dict[str, Any]:
    tracking = dict(getattr(task, "tracking", None) or {})
    policy = dict(tracking.get("policy") or build_tracking_policy(task))
    now = now_iso()
    tracking.setdefault("kind", "long_task")
    tracking.setdefault("domain", "inspection")
    tracking.setdefault("capability", "inspection")
    tracking.setdefault("source", source)
    tracking.setdefault("task_id", getattr(task, "task_id", ""))
    tracking.setdefault("workspace_id", getattr(task, "workspace_id", ""))
    tracking.setdefault("started_at", now)
    tracking.setdefault("poll_count", 0)
    tracking.setdefault("same_status_count", 0)
    tracking.setdefault("last_status", getattr(task, "status", ""))
    tracking.setdefault("last_progress_key", _progress_key(task))
    tracking.setdefault("last_progress_at", getattr(task, "started_at", "") or now)
    tracking["policy"] = policy
    tracking["status"] = getattr(task, "status", "")
    tracking["updated_at"] = now
    tracking["done"] = getattr(task, "status", "") in TERMINAL_STATUSES
    tracking["terminal"] = tracking["done"]
    tracking["next_poll_seconds"] = 0 if tracking["done"] else int(policy["poll_seconds"])
    tracking["deadline_at"] = _deadline_at(task, int(policy["deadline_seconds"]))
    tracking["progress"] = _progress(task)
    tracking["summary"] = task_summary(task)
    tracking["suggested_next_action"] = _suggested_next_action(task)
    task.tracking = tracking
    return tracking


def record_poll(task: InspectionTask, *, source: str = "tool") -> dict[str, Any]:
    tracking = ensure_tracking(task, source=source)
    prev_status = str(tracking.get("last_status") or "")
    prev_progress = str(tracking.get("last_progress_key") or "")
    current_progress = _progress_key(task)
    status = str(getattr(task, "status", "") or "")
    if prev_status == status and prev_progress == current_progress:
        tracking["same_status_count"] = int(tracking.get("same_status_count") or 0) + 1
    else:
        tracking["same_status_count"] = 0
        tracking["last_progress_at"] = now_iso()
    tracking["poll_count"] = int(tracking.get("poll_count") or 0) + 1
    tracking["last_status"] = status
    tracking["last_progress_key"] = current_progress
    tracking["last_checked_at"] = now_iso()
    tracking["stall_risk"] = (
        int(tracking.get("same_status_count") or 0)
        >= int((tracking.get("policy") or {}).get("max_same_status") or 999)
    )
    task.tracking = tracking
    return tracking


def task_summary(task: InspectionTask) -> dict[str, Any]:
    return {
        "task_id": getattr(task, "task_id", ""),
        "status": getattr(task, "status", ""),
        "total_devices": int(getattr(task, "total_assets", 0) or 0),
        "succeeded_devices": int(getattr(task, "succeeded", 0) or 0),
        "failed_devices": int(getattr(task, "failed", 0) or 0),
        "partial_devices": int(getattr(task, "partial", 0) or 0),
        "skipped_devices": int(getattr(task, "skipped", 0) or 0),
        "findings_critical": int(getattr(task, "criticals", 0) or 0),
        "findings_warning": int(getattr(task, "warnings", 0) or 0),
        "findings_info": int(getattr(task, "infos", 0) or 0),
        "duration_ms": int(getattr(task, "duration_ms", 0) or 0),
        "started_at": getattr(task, "started_at", ""),
        "finished_at": getattr(task, "finished_at", ""),
        "error": getattr(task, "error", ""),
    }


def _progress(task: InspectionTask) -> dict[str, Any]:
    total = int(getattr(task, "total_assets", 0) or 0)
    done = (
        int(getattr(task, "succeeded", 0) or 0)
        + int(getattr(task, "failed", 0) or 0)
        + int(getattr(task, "partial", 0) or 0)
        + int(getattr(task, "skipped", 0) or 0)
    )
    pct = int(min(100, round((done / total) * 100))) if total else 0
    return {"done_devices": done, "total_devices": total, "percent": pct}


def _progress_key(task: InspectionTask) -> str:
    return "|".join(str(x) for x in (
        getattr(task, "status", ""),
        getattr(task, "succeeded", 0),
        getattr(task, "failed", 0),
        getattr(task, "partial", 0),
        getattr(task, "skipped", 0),
        getattr(task, "criticals", 0),
        getattr(task, "warnings", 0),
        getattr(task, "infos", 0),
    ))


def _deadline_at(task: InspectionTask, deadline_seconds: int) -> str:
    started_at = getattr(task, "started_at", "")
    if not started_at:
        return ""
    try:
        from datetime import timedelta
        return (from_iso(started_at) + timedelta(seconds=deadline_seconds)).isoformat()
    except Exception:
        return ""


def _suggested_next_action(task: InspectionTask) -> str:
    status = str(getattr(task, "status", "") or "")
    if status in TERMINAL_STATUSES:
        if status in {"succeeded", "partial"}:
            return "fetch_report"
        return "summarize_failure"
    if getattr(task, "cancel_requested_at", ""):
        return "wait_for_cancel_drain"
    return "poll_task_get"
