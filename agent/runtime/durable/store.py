# agent/runtime/durable/store.py
"""TaskStateStore — persistence and query.

Storage: workspaces/<ws>/durable/tasks/<id>.json, events/<id>.events.json, checkpoints/<tid>/<cid>.json
"""
from __future__ import annotations
import json
import logging
import time as _time
from typing import Optional
from storage.records import append_jsonl, atomic_save_json, list_json_records, read_json_record, workspace_record_dir
from .models import TaskState, RuntimeEvent, RuntimeCheckpoint
from agent.runtime.utils import now_iso

logger = logging.getLogger(__name__)

_REDACT_KEYS = {"password","token","api_key","secret","credential","private_key","access_key","auth","authorization","x-api-token","x-admin-token"}

def _redact(obj, max_len=256):
    if isinstance(obj, dict): return {k: "[REDACTED]" if k.lower() in _REDACT_KEYS else _redact(v) for k,v in obj.items()}
    if isinstance(obj, list): return [_redact(v) for v in obj]
    if isinstance(obj, str) and len(obj) > max_len: return obj[:max_len] + "..."
    return obj

def _task_parts(task_id): return ("durable", "tasks", f"{task_id}.json")
def _events_parts(tid): return ("durable", "events", f"{tid}.events.json")
def _checkpoint_parts(tid): return ("durable", "checkpoints", tid)

# ── Task CRUD ──
def save_task(task: TaskState):
    task.updated_at = now_iso()
    atomic_save_json(task.workspace_id, _task_parts(task.task_id), task.to_dict())

def get_task(ws_id: str, task_id: str) -> Optional[TaskState]:
    data = read_json_record(ws_id, _task_parts(task_id))
    if not data: return None
    try: return TaskState.from_dict(data)
    except Exception: return None

def list_tasks(ws_id: str, session_id="", limit=50) -> list[TaskState]:
    """List tasks. P1-22: full dir scan + sort, no cache — pagination at app level."""
    if limit <= 0: return []
    tasks = []
    for data in list_json_records(ws_id, ("durable", "tasks"), limit=limit):
        try:
            t = TaskState.from_dict(data)
            if session_id and t.session_id != session_id: continue
            tasks.append(t)
            if len(tasks) >= limit: break
        except (OSError, ValueError, json.JSONDecodeError):
            # v3.9.9: a malformed TaskState file should not silently
            # skip — log it. (Continue reading remaining files.)
            logger.debug("durable: skip corrupt task record", exc_info=True)
    return tasks

# ── Events ──
def append_event(evt: RuntimeEvent):
    evt.created_at = now_iso()
    evt.payload_redacted = _redact(evt.payload_redacted)
    try:
        append_jsonl(evt.workspace_id, _events_parts(evt.task_id), evt.__dict__)
    except OSError:
        # v3.9.9: was bare ``except Exception: pass`` — losing the
        # entire event log silently hides every tool error, every
        # approval decision, every retry. Surface it at WARNING so
        # the admin sees disk pressure.
        logger.warning("durable: append_event write failed for %s",
                       evt.task_id, exc_info=True)

def get_events(ws_id, task_id, limit=100) -> list[dict]:
    path = workspace_record_dir(ws_id, "durable", "events") / f"{task_id}.events.json"
    if not path.exists(): return []
    evts = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip(): evts.append(json.loads(line))
        return evts[-limit:]
    except (OSError, json.JSONDecodeError):
        # v3.9.9: best-effort read — return what we already
        # collected before the error.
        logger.debug("durable: get_events read failed for %s", path,
                     exc_info=True)
        return evts

# ── Checkpoints ──
def save_checkpoint(cp: RuntimeCheckpoint):
    cp.created_at = now_iso()
    cp.state_snapshot = _redact(cp.state_snapshot)
    if cp.pending_action: cp.pending_action = _redact(cp.pending_action)
    atomic_save_json(cp.workspace_id, (*_checkpoint_parts(cp.task_id), f"{cp.checkpoint_id}.json"), cp.__dict__)

def get_checkpoints(ws_id, task_id) -> list[dict]:
    d = workspace_record_dir(ws_id, *_checkpoint_parts(task_id))
    if not d.exists(): return []
    cps = []
    for f in sorted(d.glob("*.json"), key=lambda x: x.stat().st_mtime):
        try:
            cps.append(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            # v3.9.9: skip + log corrupt checkpoint files.
            logger.debug("durable: skip corrupt checkpoint %s", f, exc_info=True)
    return cps
