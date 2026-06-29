# agent/runtime/durable/store.py
"""TaskStateStore — persistence and query.

Storage: workspaces/<ws>/durable/tasks/<id>.json, events/<id>.events.json, checkpoints/<tid>/<cid>.json
"""
from __future__ import annotations
import json
import logging
import time as _time
from pathlib import Path
from typing import Optional
from workspace.run_store import WS_ROOT
from workspace.atomic_io import atomic_write_json
from .models import TaskState, RuntimeEvent, RuntimeCheckpoint

logger = logging.getLogger(__name__)

_REDACT_KEYS = {"password","token","api_key","secret","credential","private_key","access_key","auth","authorization","x-api-token","x-admin-token"}

def _redact(obj, max_len=256):
    if isinstance(obj, dict): return {k: "[REDACTED]" if k.lower() in _REDACT_KEYS else _redact(v) for k,v in obj.items()}
    if isinstance(obj, list): return [_redact(v) for v in obj]
    if isinstance(obj, str) and len(obj) > max_len: return obj[:max_len] + "..."
    return obj

def _task_dir(ws): return WS_ROOT / ws / "durable" / "tasks"
def _events_path(ws, tid): return WS_ROOT / ws / "durable" / "events" / f"{tid}.events.json"
def _checkpoint_dir(ws, tid): return WS_ROOT / ws / "durable" / "checkpoints" / tid

# ── Task CRUD ──
def save_task(task: TaskState):
    task.updated_at = _time.strftime("%Y-%m-%dT%H:%M:%S", _time.localtime())
    d = _task_dir(task.workspace_id); d.mkdir(parents=True, exist_ok=True)
    atomic_write_json(d / f"{task.task_id}.json", task.to_dict())

def get_task(ws_id: str, task_id: str) -> Optional[TaskState]:
    p = _task_dir(ws_id) / f"{task_id}.json"
    if not p.exists(): return None
    try: return TaskState.from_dict(json.loads(p.read_text()))
    except Exception: return None

def list_tasks(ws_id: str, session_id="", limit=50) -> list[TaskState]:
    d = _task_dir(ws_id)
    if not d.exists() or limit <= 0: return []
    tasks = []
    for f in sorted(d.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            t = TaskState.from_dict(json.loads(f.read_text()))
            if session_id and t.session_id != session_id: continue
            tasks.append(t)
            if len(tasks) >= limit: break
        except (OSError, ValueError, json.JSONDecodeError):
            # v3.9.9: a malformed TaskState file should not silently
            # skip — log it. (Continue reading remaining files.)
            logger.debug("durable: skip corrupt task file %s", f, exc_info=True)
    return tasks

# ── Events ──
def append_event(evt: RuntimeEvent):
    evt.created_at = _time.strftime("%Y-%m-%dT%H:%M:%S", _time.localtime())
    evt.payload_redacted = _redact(evt.payload_redacted)
    p = _events_path(evt.workspace_id, evt.task_id); p.parent.mkdir(parents=True, exist_ok=True)
    try:
        with p.open("a") as fh: fh.write(json.dumps(evt.__dict__, ensure_ascii=False, default=str) + "\n")
    except OSError:
        # v3.9.9: was bare ``except Exception: pass`` — losing the
        # entire event log silently hides every tool error, every
        # approval decision, every retry. Surface it at WARNING so
        # the admin sees disk pressure.
        logger.warning("durable: append_event write failed for %s",
                       p, exc_info=True)

def get_events(ws_id, task_id, limit=100) -> list[dict]:
    p = _events_path(ws_id, task_id)
    if not p.exists(): return []
    evts = []
    try:
        for line in p.read_text().splitlines():
            if line.strip(): evts.append(json.loads(line))
        return evts[-limit:]
    except (OSError, json.JSONDecodeError):
        # v3.9.9: best-effort read — return what we already
        # collected before the error.
        logger.debug("durable: get_events read failed for %s", p,
                     exc_info=True)
        return evts

# ── Checkpoints ──
def save_checkpoint(cp: RuntimeCheckpoint):
    cp.created_at = _time.strftime("%Y-%m-%dT%H:%M:%S", _time.localtime())
    cp.state_snapshot = _redact(cp.state_snapshot)
    if cp.pending_action: cp.pending_action = _redact(cp.pending_action)
    d = _checkpoint_dir(cp.workspace_id, cp.task_id); d.mkdir(parents=True, exist_ok=True)
    atomic_write_json(d / f"{cp.checkpoint_id}.json", cp.__dict__)

def get_checkpoints(ws_id, task_id) -> list[dict]:
    d = _checkpoint_dir(ws_id, task_id)
    if not d.exists(): return []
    cps = []
    for f in sorted(d.glob("*.json"), key=lambda x: x.stat().st_mtime):
        try:
            cps.append(json.loads(f.read_text()))
        except (OSError, json.JSONDecodeError):
            # v3.9.9: skip + log corrupt checkpoint files.
            logger.debug("durable: skip corrupt checkpoint %s", f, exc_info=True)
    return cps
