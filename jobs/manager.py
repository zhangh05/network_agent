# jobs/manager.py
"""Job manager — high-level job lifecycle operations."""

import time, traceback
from jobs.schemas import JobRecord, JobEvent, JobProgress, ENABLED_JOB_TYPES, JOB_STATUSES
from jobs.store import create_job as _create, get_job, update_job, append_event, append_log


def create_job(workspace_id="default", job_type="agent_run", title="", payload=None,
               input_artifacts=None, created_by="user", enqueue=True) -> JobRecord:
    if job_type not in ENABLED_JOB_TYPES and job_type not in ("batch_translate_config",):
        raise ValueError(f"unsupported job_type: {job_type}")

    rec = JobRecord(
        workspace_id=workspace_id, job_type=job_type,
        title=title or f"{job_type} job",
        payload=payload or {},
        input_artifacts=input_artifacts or [],
        created_by=created_by,
        status="created",
    )
    rec = _create(rec)
    if enqueue:
        rec = enqueue_job(workspace_id, rec.job_id)
    return rec


def enqueue_job(ws_id, job_id) -> JobRecord:
    rec = _transition(ws_id, job_id, "queued", event_type="job_queued", message="Job queued")
    return rec


def cancel_job(ws_id, job_id) -> JobRecord:
    rec = get_job(ws_id, job_id)
    if not rec:
        raise ValueError("job not found")
    if rec.status == "queued":
        append_event(ws_id, job_id, JobEvent(job_id=job_id, workspace_id=ws_id,
                     event_type="job_cancelled", message="Job cancelled from queue"))
        return _transition(ws_id, job_id, "cancelled", event_type="job_cancelled")
    elif rec.status == "running":
        result = update_job(ws_id, job_id, {"cancel_requested": True})
        append_event(ws_id, job_id, JobEvent(job_id=job_id, workspace_id=ws_id,
                     event_type="job_cancel_requested", message="Cancel requested"))
        return result
    return rec


def retry_job(ws_id, job_id) -> JobRecord:
    rec = get_job(ws_id, job_id)
    if not rec:
        raise ValueError("job not found")
    if rec.status not in ("failed", "cancelled"):
        raise ValueError(f"cannot retry job with status {rec.status}")
    if rec.retry_count >= rec.max_retries:
        raise ValueError("max retries exceeded")
    patch = {"retry_count": rec.retry_count + 1, "status": "queued",
             "error": "", "cancel_requested": False}
    result = update_job(ws_id, job_id, patch)
    append_event(ws_id, job_id, JobEvent(job_id=job_id, workspace_id=ws_id,
                 event_type="job_retried", message=f"Retry #{rec.retry_count + 1}"))
    return result


def mark_running(ws_id, job_id) -> JobRecord:
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    rec = _transition(ws_id, job_id, "running", event_type="job_started", message="Job started")
    if rec:
        update_job(ws_id, job_id, {"started_at": now})
    return rec


def mark_succeeded(ws_id, job_id, result_summary=None) -> JobRecord:
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    patch = {"status": "succeeded", "finished_at": now}
    if result_summary:
        patch["result_summary"] = result_summary
    rec = update_job(ws_id, job_id, patch)
    if rec:
        append_event(ws_id, job_id, JobEvent(job_id=job_id, workspace_id=ws_id,
                     event_type="job_succeeded", message="Job succeeded"))
    return rec


def mark_failed(ws_id, job_id, error="") -> JobRecord:
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    error = str(error)[:500]
    rec = update_job(ws_id, job_id, {"status": "failed", "finished_at": now, "error": error})
    if rec:
        append_event(ws_id, job_id, JobEvent(job_id=job_id, workspace_id=ws_id,
                     event_type="job_failed", message=f"Job failed: {error[:100]}"))
    return rec


def update_progress(ws_id, job_id, current=None, total=None, message="", step=""):
    rec = get_job(ws_id, job_id)
    if not rec: return
    prog = rec.progress or {}
    if current is not None: prog["current"] = current
    if total is not None: prog["total"] = total
    if total: prog["percent"] = min(100, int((prog.get("current", 0) / total) * 100))
    if message: prog["message"] = message
    if step: prog["current_step"] = step
    prog["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    update_job(ws_id, job_id, {"progress": prog})
    append_event(ws_id, job_id, JobEvent(job_id=job_id, workspace_id=ws_id,
                 event_type="job_progress", message=message or f"Progress: {prog.get('current',0)}/{prog.get('total',0)}",
                 progress=dict(prog)))


def _transition(ws_id, job_id, target_status, event_type="", message=""):
    patch = {"status": target_status}
    rec = update_job(ws_id, job_id, patch)
    if rec:
        append_event(ws_id, job_id, JobEvent(job_id=job_id, workspace_id=ws_id,
                     event_type=event_type, message=message))
    return rec
