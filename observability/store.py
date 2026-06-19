# observability/store.py
"""Trace store — write/read trace records to workspace runs directory."""

import json
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Optional


def _get_ws_root():
    """Get workspace root (deferred, respects test monkeypatches)."""
    try:
        from workspace.manager import WS_ROOT
        return WS_ROOT
    except ImportError:
        return Path(__file__).resolve().parent.parent / "workspaces"


# P1 fix (round 7): delegate atomic writes to workspace.atomic_io so
# they share the pid+uuid tmp-name scheme and O_EXCL protection added
# in round 7. Keeps concurrent writes from clobbering each other's
# tmp file (a known issue with the previous `.tmp` suffix collision).
def _atomic_write_json(path: Path, data: dict) -> None:
    from workspace.atomic_io import atomic_write_json as _atomic
    _atomic(path, data, indent=2)


_trace_locks: dict[str, threading.RLock] = {}
_trace_locks_guard = threading.Lock()


def _thread_lock_for(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _trace_locks_guard:
        lock = _trace_locks.get(key)
        if lock is None:
            lock = threading.RLock()
            _trace_locks[key] = lock
        return lock


@contextmanager
def _locked_trace(path: Path):
    """Serialize trace read-modify-write across threads and POSIX workers."""
    lock_path = path.with_name(path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with _thread_lock_for(path):
        lock_file = lock_path.open("a+")
        try:
            try:
                import fcntl
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            except (ImportError, OSError):
                pass
            yield
        finally:
            try:
                import fcntl
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            except (ImportError, OSError):
                pass
            lock_file.close()


def write_trace(trace, ws_id: str = "default") -> str:
    """Write a trace record to workspace runs directory. Returns trace_id."""
    from workspace.manager import ensure_workspace
    ws_id = ensure_workspace(ws_id)

    trace_id = trace.trace_id
    run_id = trace.run_id

    WS_ROOT = _get_ws_root()
    runs_dir = WS_ROOT / ws_id / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    # Redact before writing
    from observability.redaction import redact_trace
    data = redact_trace(trace.as_dict())

    path = runs_dir / f"{run_id}.trace.json"
    _atomic_write_json(path, data)

    return trace_id


def get_trace(run_id: str, ws_id: str = "default") -> Optional[dict]:
    """Get a trace record by run_id."""
    from workspace.ids import validate_workspace_id
    ws_id = validate_workspace_id(ws_id)
    WS_ROOT = _get_ws_root()
    path = WS_ROOT / ws_id / "runs" / f"{run_id}.trace.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def list_traces(ws_id: str = "default", limit: int = 50) -> list:
    """List trace records for a workspace."""
    from workspace.ids import validate_workspace_id
    ws_id = validate_workspace_id(ws_id)
    WS_ROOT = _get_ws_root()
    runs_dir = WS_ROOT / ws_id / "runs"
    if not runs_dir.is_dir():
        return []

    traces = []
    for f in sorted(runs_dir.glob("*.trace.json"), reverse=True):
        try:
            trace = json.loads(f.read_text())
            traces.append({
                "trace_id": trace.get("trace_id", ""),
                "run_id": trace.get("run_id", ""),
                "workspace_id": trace.get("workspace_id", ""),
                "status": trace.get("status", ""),
                "total_duration_ms": trace.get("total_duration_ms", 0),
                "node_count": trace.get("node_count", 0),
                "event_count": len(trace.get("events", [])),
            })
            if len(traces) >= limit:
                break
        except Exception:
            pass
    return traces


def append_event(trace_id: str, event, ws_id: str = "default"):
    """Append an event to an existing trace.

    Performs an O(n) lookup via filename-derived hint first, falling
    back to a single directory scan if the hint path is missing.
    Atomic via tmp + os.replace().
    """
    from workspace.ids import validate_workspace_id
    ws_id = validate_workspace_id(ws_id)
    WS_ROOT = _get_ws_root()
    runs_dir = WS_ROOT / ws_id / "runs"
    if not runs_dir.is_dir():
        return

    # Cheap filename-derived hint: most callers know run_id, so
    # try that path first to avoid scanning the whole runs dir.
    target = None
    if hasattr(event, "run_id") and getattr(event, "run_id", None):
        candidate = runs_dir / f"{event.run_id}.trace.json"
        if candidate.is_file():
            try:
                d = json.loads(candidate.read_text())
                if d.get("trace_id") == trace_id:
                    target = candidate
            except Exception:
                target = None

    if target is None:
        for path in sorted(runs_dir.glob("*.trace.json"), reverse=True):
            try:
                d = json.loads(path.read_text())
                if d.get("trace_id") == trace_id:
                    target = path
                    break
            except Exception:
                continue

    if target is None:
        return

    try:
        with _locked_trace(target):
            data = json.loads(target.read_text())
            from observability.redaction import redact_trace_event
            events = data.get("events", [])
            event_data = event.as_dict() if hasattr(event, "as_dict") else event
            events.append(redact_trace_event(event_data))
            data["events"] = events
            _atomic_write_json(target, data)
    except Exception:
        pass
