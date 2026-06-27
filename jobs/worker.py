# jobs/worker.py
"""Local worker — poll queued jobs and execute them.

Locking: fcntl.flock is used for cross-process advisory locking.
It releases automatically when the process exits or unlocks the fd,
providing crash-safe mutual exclusion without stale lock detection.
"""

import fcntl
import json
import os
import time
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

    # Acquire lock via fcntl.flock (crash-safe: released on process exit)
    RUNTIME.mkdir(parents=True, exist_ok=True)
    try:
        lock_fd = os.open(LOCK_PATH, os.O_CREAT | os.O_RDWR)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(lock_fd)
            return {"status": "locked", "message": "Another worker is running"}
    except OSError:
        return {"status": "error", "message": "Failed to acquire lock"}

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
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
        # Clean up lock file
        try:
            LOCK_PATH.unlink(missing_ok=True)
        except Exception:
            pass


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
