# jobs/store.py
"""Job store — CRUD for jobs, events, logs in workspace directories."""

import json, os, time, shutil
from pathlib import Path
from typing import Optional

from jobs.schemas import JobRecord, JobEvent
from jobs.redaction import (
    sanitize_job_record_for_storage, sanitize_job_record_for_api,
    sanitize_job_event_for_storage, sanitize_job_event_for_api,
    sanitize_job_log_for_storage, sanitize_job_log_for_api,
)

ROOT = Path(__file__).resolve().parent.parent

def _get_ws_root():
    try:
        from workspace.manager import WS_ROOT as w
        return w
    except Exception:
        return ROOT / "workspaces"

def _job_dir(ws_id, job_id=""):
    from workspace.ids import validate_workspace_id
    ws_id = validate_workspace_id(ws_id)
    return _get_ws_root() / ws_id / "jobs" / (job_id if job_id else "")

def _ensure(ws_id, job_id=""):
    d = _job_dir(ws_id, job_id)
    d.mkdir(parents=True, exist_ok=True)
    return d

def _index_path(ws_id):
    from workspace.ids import validate_workspace_id
    ws_id = validate_workspace_id(ws_id)
    return _get_ws_root() / ws_id / "sys" / "jobs.index.json"


def create_job(rec: JobRecord) -> JobRecord:
    from workspace.manager import ensure_workspace
    ensure_workspace(rec.workspace_id)
    d = _ensure(rec.workspace_id, rec.job_id)
    # Sanitize before writing to disk
    safe = sanitize_job_record_for_storage(rec.as_dict())
    _write_atomic(d / f"{rec.job_id}.json", json.dumps(safe, indent=2, ensure_ascii=False))
    # Apply sanitization to rec before returning
    for k, v in safe.items():
        if hasattr(rec, k):
            setattr(rec, k, v)
    _update_index(rec.workspace_id, rec)
    append_event(rec.workspace_id, rec.job_id,
                 JobEvent(job_id=rec.job_id, workspace_id=rec.workspace_id,
                          event_type="job_created", message=f"Job created: {rec.title}"))
    _update_workspace_stats(rec.workspace_id)
    return rec


def get_job(ws_id, job_id) -> Optional[JobRecord]:
    if not job_id:
        return None
    path = _job_dir(ws_id, job_id) / f"{job_id}.json"
    if not path.is_file(): return None
    try:
        d = json.loads(path.read_text())
        return JobRecord(**{k: v for k, v in d.items() if k in JobRecord.__dataclass_fields__})
    except json.JSONDecodeError:
        import logging
        logging.getLogger("jobs.store").error("corrupt job file: %s", path)
        return None
    except Exception:
        import logging
        logging.getLogger("jobs.store").exception("unexpected error reading job: %s", path)
        return None


def update_job(ws_id, job_id, patch: dict) -> Optional[JobRecord]:
    rec = get_job(ws_id, job_id)
    if not rec: return None
    for k, v in patch.items():
        if hasattr(rec, k):
            setattr(rec, k, v)
    rec.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    d = _ensure(ws_id, job_id)
    safe = sanitize_job_record_for_storage(rec.as_dict())
    _write_atomic(d / f"{job_id}.json", json.dumps(safe, indent=2, ensure_ascii=False))
    for k, v in safe.items():
        if hasattr(rec, k):
            setattr(rec, k, v)
    _update_workspace_stats(ws_id)
    return rec


def _session_exists(ws_id, session_id):
    """Check if a session still exists and is not soft-deleted.
    
    Sessions can exist in two forms:
    1. {session_id}.json  — session metadata file
    2. {session_id}/      — session directory with messages/
    
    A session is considered alive if either form exists AND it's not marked deleted.
    """
    if not session_id:
        return False
    base = _get_ws_root() / ws_id / "sessions"
    meta_file = base / f"{session_id}.json"
    meta_dir  = base / str(session_id)
    
    # Must have at least one form of session storage
    if not meta_file.is_file() and not meta_dir.is_dir():
        return False
    
    # If metadata file exists, check it's not deleted
    if meta_file.is_file():
        try:
            d = json.loads(meta_file.read_text())
            if d.get("status", "active") == "deleted":
                return False
        except Exception:
            pass  # corrupt file → treat as exists
    
    return True


def list_jobs(ws_id=None, status=None, job_type=None, limit=100) -> list:
    results = []
    ws_root = _get_ws_root()
    if ws_id:
        from workspace.ids import validate_workspace_id
        ws_id = validate_workspace_id(ws_id)
    for wd in ws_root.iterdir() if not ws_id else [ws_root / ws_id]:
        if not wd.is_dir() or wd.name.startswith("."): continue
        jd = wd / "jobs"
        if not jd.is_dir(): continue
        for f in sorted(jd.glob("*/*.json"), reverse=True):
            if not f.name.endswith("_meta.json") and "events" not in str(f) and "log" not in str(f):
                j = get_job(wd.name, f.stem)
                if not j: continue
                if ws_id and j.workspace_id != ws_id: continue
                if status and j.status != status: continue
                if job_type and j.job_type != job_type: continue
                # Filter out agent_run jobs whose session no longer exists
                if j.job_type == "agent_run":
                    sid = (j.payload or {}).get("session_id", "")
                    if sid and not _session_exists(wd.name, sid):
                        continue
                results.append(sanitize_job_record_for_api(j.as_dict()))
                if len(results) >= limit: break
    return results


def delete_job(ws_id, job_id, soft=True) -> bool:
    if not job_id:
        raise ValueError("job_id is required for delete_job")
    if soft:
        return bool(update_job(ws_id, job_id, {"status": "cancelled", "cancel_requested": True}))
    shutil.rmtree(_job_dir(ws_id, job_id), ignore_errors=True)
    return True


def append_event(ws_id, job_id, event: JobEvent) -> JobEvent:
    _ensure(ws_id, job_id)
    p = _job_dir(ws_id, job_id) / f"{job_id}.events.jsonl"
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(sanitize_job_event_for_storage(event.as_dict()), ensure_ascii=False) + "\n")
    return event


def list_events(ws_id, job_id, limit=200) -> list:
    p = _job_dir(ws_id, job_id) / f"{job_id}.events.jsonl"
    if not p.is_file(): return []
    events = []
    for line in p.read_text().strip().split("\n"):
        if not line: continue
        try:
            events.append(json.loads(line))
        except Exception:
            _LOG.warning("jobs.store: silent exception", exc_info=True)
    return events[-limit:]


def append_log(ws_id, job_id, message, level="info", meta=None):
    _ensure(ws_id, job_id)
    p = _job_dir(ws_id, job_id) / f"{job_id}.log.jsonl"
    entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "level": level,
             "msg": message[:1000], "meta": meta or {}}
    # Sanitize before writing
    safe = sanitize_job_log_for_storage(entry)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(safe, ensure_ascii=False) + "\n")


def list_logs(ws_id, job_id, limit=200) -> list:
    p = _job_dir(ws_id, job_id) / f"{job_id}.log.jsonl"
    if not p.is_file(): return []
    logs = []
    for line in p.read_text().strip().split("\n"):
        if not line: continue
        try:
            logs.append(json.loads(line))
        except Exception:
            _LOG.warning("jobs.store: silent exception", exc_info=True)
    return logs[-limit:]


def get_next_queued_job() -> Optional[JobRecord]:
    ws_root = _get_ws_root()
    for wd in sorted(ws_root.iterdir(), reverse=True):
        if not wd.is_dir(): continue
        jd = wd / "jobs"
        if not jd.is_dir(): continue
        for f in sorted(jd.glob("*/*.json")):
            j = get_job(wd.name, f.stem)
            if j and j.status == "queued": return j
    return None


# ── helpers ──

def _update_index(ws_id, rec):
    p = _index_path(ws_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    idx = {"job_ids": [], "updated_at": ""}
    if p.is_file():
        try:
            idx = json.loads(p.read_text())
        except Exception:
            _LOG.warning("jobs.store: silent exception", exc_info=True)
    if rec.job_id not in idx.setdefault("job_ids", []):
        idx["job_ids"].append(rec.job_id)
    idx["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    p.write_text(json.dumps(idx, indent=2, ensure_ascii=False))

def _write_atomic(path, content):
    tmp = str(path) + ".tmp." + str(int(time.time()))
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp, str(path))

def _update_workspace_stats(ws_id):
    """Update workspace state with job counts."""
    try:
        from workspace.manager import update_workspace_state
        jobs = list_jobs(ws_id=ws_id, limit=500)
        status_counts = {}
        for j in jobs:
            s = j.get("status", "")
            status_counts[s] = status_counts.get(s, 0) + 1
        counts = {
            "jobs_count": len(jobs),
            "queued_jobs_count": status_counts.get("queued", 0),
            "running_jobs_count": status_counts.get("running", 0),
            "succeeded_jobs_count": status_counts.get("succeeded", 0),
            "failed_jobs_count": status_counts.get("failed", 0),
            "cancelled_jobs_count": status_counts.get("cancelled", 0),
            "last_job_id": jobs[0]["job_id"] if jobs else "",
            "recent_jobs": [{"job_id": j.get("job_id"), "job_type": j.get("job_type"),
                             "title": j.get("title"), "status": j.get("status"),
                             "updated_at": j.get("updated_at")} for j in jobs[:5]],
        }
        update_workspace_state(ws_id, {"job_stats": counts})
    except Exception:
        _LOG.warning("jobs.store: silent exception", exc_info=True)
