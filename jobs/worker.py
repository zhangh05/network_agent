# jobs/worker.py
"""Local worker — poll queued jobs and execute them."""

import json, time, os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNTIME = ROOT / "runtime" / "jobs"
LOCK_PATH = RUNTIME / "worker.lock"
STATE_PATH = RUNTIME / "worker_state.json"

_worker_active = False


def start_worker(poll_interval=1.0):
    global _worker_active
    _worker_active = True
    RUNTIME.mkdir(parents=True, exist_ok=True)
    while _worker_active:
        try:
            run_once()
        except Exception:
            pass
        time.sleep(poll_interval)


def stop_worker():
    global _worker_active
    _worker_active = False


def run_once() -> dict:
    """Poll and execute one queued job. Returns result."""
    from jobs.store import get_next_queued_job
    from jobs.runner import run_job

    # Acquire lock
    RUNTIME.mkdir(parents=True, exist_ok=True)
    if LOCK_PATH.exists():
        # Check if stale (>30s)
        age = time.time() - LOCK_PATH.stat().st_mtime
        if age < 30:
            return {"status": "locked", "message": "Another worker is running"}
        LOCK_PATH.unlink()

    LOCK_PATH.write_text(str(os.getpid()))

    try:
        job = get_next_queued_job()
        if not job:
            _write_state({"status": "idle", "message": "No queued jobs"})
            return {"status": "idle", "message": "No queued jobs"}

        _write_state({"status": "running", "job_id": job.job_id, "job_type": job.job_type})
        run_job(job.workspace_id, job.job_id)
        _write_state({"status": "completed", "job_id": job.job_id, "job_type": job.job_type})
        return {"status": "completed", "job_id": job.job_id}
    finally:
        if LOCK_PATH.exists():
            LOCK_PATH.unlink()


def get_worker_state() -> dict:
    if STATE_PATH.is_file():
        try:
            return json.loads(STATE_PATH.read_text())
        except Exception:
            pass
    return {"status": "idle"}


def _write_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False))
