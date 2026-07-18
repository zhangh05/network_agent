# jobs/worker.py
"""Local worker — poll queued jobs and execute them.

Locking: fcntl.flock is used for cross-process advisory locking.
It releases automatically when the process exits or unlocks the fd,
providing crash-safe mutual exclusion without stale lock detection.
"""

import os
import time

from storage.time_utils import now_iso
from storage.atomic_io import atomic_write_text

_worker_active = False


def _runtime_dir():
    from storage.paths import runtime_root

    path = runtime_root() / "jobs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _lock_path():
    return _runtime_dir() / "worker.lock"


def start_worker(poll_interval=1.0):
    global _worker_active
    _worker_active = True
    _runtime_dir()
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

    lock_path = _lock_path()

    # Acquire lock: fcntl.flock on POSIX, mtime-based fallback on Windows
    try:
        import fcntl
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(lock_fd)
            return {"status": "locked", "message": "Another worker is running"}
        _release_lock = lambda: (fcntl.flock(lock_fd, fcntl.LOCK_UN), os.close(lock_fd))
    except (ImportError, OSError):
        lock_fd = lock_path
        if lock_path.exists():
            age = time.time() - lock_path.stat().st_mtime
            if age < 30:
                return {"status": "locked", "message": "Another worker is running"}
            lock_path.unlink()
        atomic_write_text(lock_path, str(os.getpid()))
        _release_lock = lambda: lock_path.unlink(missing_ok=True) if lock_path.exists() else None

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
        _release_lock()


def get_worker_state() -> dict:
    from storage.runtime_state_store import read_runtime_record

    return read_runtime_record("jobs_worker_state") or {"status": "idle"}


def _write_state(state):
    from storage.runtime_state_store import save_runtime_record

    state["updated_at"] = now_iso()
    save_runtime_record("jobs_worker_state", state)
