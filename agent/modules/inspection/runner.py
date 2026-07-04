"""agent.modules.inspection.runner

Orchestrates the per-asset, per-check pipeline. We deliberately
keep all side effects funneled through the canonical tool layer
(``exec.run`` and ``device.manage``) so:

  1. Passwords stay server-side — the runner never sees
     cleartext credentials. ``asset_id`` resolves them through
     the existing CMDB path.
  2. Destructive-command checks still apply to the inspection
     surface (we never feed raw LLM string commands; commands
     come from a fixed ``VendorCommandProfile`` map).
  3. Audit hooks (TraceRecorder / EventRecorder) see the calls
     and credit them to the inspection task.

v3.10 (inspection): per-device concurrency lives in a
``ThreadPoolExecutor`` (single device = sequential). Cancellation
is cooperative — the per-check loop polls ``_CANCEL_REQUESTS``.
Per-task ``_save_task`` calls serialise under a per-task lock so
the worker pool never races the same task file.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from agent.runtime.utils import now_iso, from_iso, duration_ms
from artifacts.store import save_artifact
from core.tools.redaction import redact_string
from core.tools.context import ToolRuntimeContext
from core.tools.integration import get_default_tool_runtime_client
from core.tools.schemas import ToolInvocation

from .models import (
    CommandResult,
    DeviceResult,
    Finding,
    InspectionProfile,
    InspectionScope,
    InspectionTask,
)
from .profiles import (
    BUILTIN_PROFILES,
    AUTO_PROFILE_ID,
    resolve_auto_profile,
    resolve_profile,
    load_command_profile,
    is_read_only_command,
)
from .tracking import ensure_tracking, record_poll


# v3.10 (inspection): caller identifier for the canonical
# ToolRuntimeClient. The exec.run and device.manage manifests are
# extended with this caller.
INSPECTION_CALLER = "inspection_runner"


# ── cancellation registry ──────────────────────────────────────────────
# Tasks run in worker threads. An LLM-side cancel request lands here;
# the per-asset / per-check loops poll it. Cancellation is cooperative:
# in-flight commands finish, no new checks are dispatched.

_CANCEL_LOCK = threading.Lock()
# (workspace_id, task_id) -> cancel_requested_at (ISO str, set by
# cancel_task). v3.10: scoped by workspace so the namespace doesn't
# collide when two workspaces happen to use the same task_id (UUID
# already makes a collision astronomically unlikely, but scoping is
# free defence-in-depth).
_CANCEL_REQUESTS: dict[tuple[str, str], str] = {}
_TASK_SESSION_LOCK = threading.Lock()
# workspace_id -> task_id -> session_id -> protocol
_TASK_SESSIONS: dict[str, dict[str, dict[str, str]]] = {}
# Per-task save lock so concurrent device workers serialise their
# progress saves. Without this the ThreadPoolExecutor can race the
# same task to disk and the second save can revert a newer state.
# v3.10 (inspection): each task gets its own lock lazily.
_TASK_SAVE_LOCKS: dict[str, threading.Lock] = {}
_TASK_SAVE_LOCKS_GUARD = threading.Lock()


def _cancel_requested(workspace_id: str, task_id: str) -> bool:
    """Return True if the task has been flagged for cancellation."""
    if not task_id:
        return False
    key = (workspace_id or "", task_id)
    with _CANCEL_LOCK:
        return key in _CANCEL_REQUESTS


def _consume_cancel_marker(workspace_id: str, task_id: str) -> str:
    """Return and clear the cancel-requested ISO timestamp."""
    if not task_id:
        return ""
    key = (workspace_id or "", task_id)
    with _CANCEL_LOCK:
        return _CANCEL_REQUESTS.pop(key, "")


def _register_task_session(workspace_id: str, task_id: str, protocol: str, session_id: str) -> None:
    """Remember a live remote session owned by an inspection task.

    v3.10: namespace is ``workspace_id -> task_id -> session_id`` so
    two workspaces can't see each other's sessions.
    """
    if not task_id or not workspace_id or not session_id:
        return
    normalized_protocol = "telnet" if (protocol or "").lower() == "telnet" else "ssh"
    with _TASK_SESSION_LOCK:
        _TASK_SESSIONS.setdefault(workspace_id, {}).setdefault(
            task_id, {}
        )[session_id] = normalized_protocol


def _forget_task_session(workspace_id: str, task_id: str, session_id: str) -> None:
    if not task_id or not session_id:
        return
    with _TASK_SESSION_LOCK:
        tasks = _TASK_SESSIONS.get(workspace_id)
        if not tasks:
            return
        sessions = tasks.get(task_id)
        if not sessions:
            return
        sessions.pop(session_id, None)
        if not sessions:
            tasks.pop(task_id, None)
        if not tasks:
            _TASK_SESSIONS.pop(workspace_id, None)


def _registered_task_sessions(workspace_id: str, task_id: str) -> dict[str, str]:
    """Return a copy of ``{session_id: protocol}`` for cancel paths."""
    with _TASK_SESSION_LOCK:
        return dict(_TASK_SESSIONS.get(workspace_id, {}).get(task_id, {}))


# ── storage ──────────────────────────────────────────────────────────────

def _inspection_root(workspace_id: str):
    from workspace.run_store import WS_ROOT
    from workspace.ids import validate_workspace_id
    return WS_ROOT / validate_workspace_id(workspace_id) / "inspection"


def _task_path(workspace_id: str, task_id: str):
    return _inspection_root(workspace_id) / "tasks" / f"{task_id}.json"


def _get_task_save_lock(task_id: str) -> threading.Lock:
    """Return (lazily create) a per-task save lock.

    v3.10 (inspection): device workers running in a ThreadPoolExecutor
    each call ``_save_task`` when they finish. Without serialising on
    a per-task lock the writes can race and the second writer
    reverts the merged ``task.devices`` state. We keep one lock per
    task so unrelated tasks don't block each other.
    """
    with _TASK_SAVE_LOCKS_GUARD:
        lock = _TASK_SAVE_LOCKS.get(task_id)
        if lock is None:
            lock = threading.Lock()
            _TASK_SAVE_LOCKS[task_id] = lock
        return lock


def _release_task_save_lock(task_id: str) -> None:
    """Drop the per-task save lock when the task is finalised.

    Bounded cleanup so a long-running backend doesn't accumulate
    locks for every task ever started.
    """
    with _TASK_SAVE_LOCKS_GUARD:
        _TASK_SAVE_LOCKS.pop(task_id, None)


def _save_task_unlocked(workspace_id: str, task: InspectionTask) -> None:
    """Inner save helper used by both ``_save_task`` and
    :func:`_record_device` (which already holds the per-task save
    lock). Splits the file-write body from the lock-acquisition
    path so ``_record_device`` can take the lock once, snap the
    ``task.devices`` dict, and save without nested acquisition.
    """
    from workspace.atomic_io import atomic_write_json
    p = _task_path(workspace_id, task.task_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    from dataclasses import asdict
    ensure_tracking(task, source="runner")
    if task.started_at and task.finished_at:
        try:
            task.duration_ms = int((from_iso(task.finished_at)
                                    - from_iso(task.started_at)).total_seconds() * 1000)
        except Exception:
            task.duration_ms = 0
            logger.debug(
                "inspection._save_task: bad timestamps "
                "started_at=%r finished_at=%r",
                task.started_at, task.finished_at,
                exc_info=True,
            )
    atomic_write_json(p, asdict(task))


def _save_task(workspace_id: str, task: InspectionTask) -> None:
    """Persist the task to disk under a per-task save lock.

    v3.10 (inspection): device workers run in parallel; multiple
    writers can hit the same task file at once. The atomic write
    itself is file-level safe, but the in-memory mutation of
    ``task.devices`` / ``task.duration_ms`` is not — two threads
    can each read a stale view of the dict, then one save overwrites
    the other. The per-task lock collapses the read-modify-write
    window so progress saves are always monotonic.
    """
    with _get_task_save_lock(task.task_id):
        _save_task_unlocked(workspace_id, task)


def _task_duration_ms(task: InspectionTask) -> int:
    """Recompute duration_ms from the canonical timestamps.

    Avoids hand-maintained drift; the persisted value is the one we
    write at task finalization.
    """
    if not task.started_at or not task.finished_at:
        return 0
    try:
        return int((from_iso(task.finished_at)
                     - from_iso(task.started_at)).total_seconds() * 1000)
    except Exception:
        logger.debug(
            "inspection._task_duration_ms: bad timestamps "
            "started_at=%r finished_at=%r",
            getattr(task, "started_at", ""),
            getattr(task, "finished_at", ""),
            exc_info=True,
        )
        return 0


def reconcile_phantom_running_tasks(workspace_id: str, root_override=None) -> int:
    """Mark any disk-resident tasks left in 'running' state as
    'crashed'. Called on backend startup so a SIGKILL'd inspection
    does not show phantom-running tasks forever.

    Returns the number of tasks flipped. ``root_override`` lets
    tests target a tmp directory without monkey-patching module
    globals.
    """
    from workspace.atomic_io import safe_read_json, atomic_write_json
    from .models import InspectionTask
    if root_override is not None:
        root = root_override / workspace_id / "inspection" / "tasks"
    else:
        root = _inspection_root(workspace_id) / "tasks"
    if not root.exists():
        return 0
    flipped = 0
    for p in root.glob("ins_*.json"):
        try:
            data = safe_read_json(p, default=None)
        except Exception:
            continue
        if not data:
            continue
        if data.get("status") != "running":
            continue
        data["status"] = "crashed"
        data["error"] = (data.get("error", "")
                          or "backend_restart_during_run")
        data["finished_at"] = now_iso()
        from dataclasses import asdict
        try:
            atomic_write_json(p, data)
            flipped += 1
        except Exception:
            logger.debug("reconcile_phantom: write failed", exc_info=True)
    return flipped


def reconcile_all_workspaces(root=None) -> dict:
    """Sweep every workspace for phantom-running inspection tasks.

    Returns a per-workspace count summary; safe to call on backend
    startup. ``root`` (optional) overrides ``WS_ROOT`` for tests.
    """
    from workspace.run_store import WS_ROOT
    root = WS_ROOT if root is None else root
    out: dict = {}
    if not root.exists():
        return out
    for ws_dir in root.iterdir():
        if not ws_dir.is_dir() or ws_dir.name.startswith("_"):
            continue
        try:
            from workspace.ids import validate_workspace_id
            ws = validate_workspace_id(ws_dir.name)
        except Exception:
            continue
        n = reconcile_phantom_running_tasks(ws, root_override=root)
        if n:
            out[ws] = n
    return out


def load_task(workspace_id: str, task_id: str) -> Optional[InspectionTask]:
    from workspace.atomic_io import safe_read_json
    from .models import InspectionScope, DeviceResult  # noqa: F401 (for type chain)
    p = _task_path(workspace_id, task_id)
    data = safe_read_json(p, default=None)
    if not data:
        return None
    return _task_from_dict(data)


def list_tasks(workspace_id: str, *, limit: int = 50) -> list:
    root = _inspection_root(workspace_id) / "tasks"
    if not root.exists():
        return []
    out: list[dict] = []
    for p in sorted(root.glob("*.json"), reverse=True):
        from workspace.atomic_io import safe_read_json
        d = safe_read_json(p, default=None)
        if d:
            out.append(d)
        if len(out) >= limit:
            break
    return out


def record_tracking_poll(workspace_id: str, task_id: str, *, source: str = "tool") -> Optional[InspectionTask]:
    """Load a task, record an observer poll, persist, and return it."""
    task = load_task(workspace_id, task_id)
    if task is None:
        return None
    record_poll(task, source=source)
    _save_task(workspace_id, task)
    return task


def _task_from_dict(d: dict) -> InspectionTask:
    """Construct InspectionTask from a serialized dict.

    Dataclass field-name round-trip via InspectionScope / DeviceResult
    construction; nested device.results round-trip via dict and model
    rebuild keeps the on-disk shape simple.

    v3.10: the per-device ``setattr`` is restricted to known
    :class:`DeviceResult` fields so an unknown JSON key (typo or
    removed/experimental column) can't be injected onto a live
    dataclass. Unknown keys are dropped with a single warning per
    task, not per device, to keep the log readable.
    """
    scope_raw = d.get("scope", {}) or {}
    scope = InspectionScope(
        region=scope_raw.get("region", ""),
        location=scope_raw.get("location", ""),
        search=scope_raw.get("search", ""),
        type=scope_raw.get("type", ""),
        vendor=scope_raw.get("vendor", ""),
        tags=tuple(scope_raw.get("tags", []) or []),
        asset_ids=tuple(scope_raw.get("asset_ids", []) or []),
        limit=scope_raw.get("limit", 50),
    )
    _dr_known = set(f.name for f in __import__("dataclasses").fields(DeviceResult))
    _unknown_seen: set[str] = set()
    devices: dict[str, DeviceResult] = {}
    for aid, dev in (d.get("devices") or {}).items():
        dr = DeviceResult(task_id=d.get("task_id", ""), asset_id=aid)
        for k, v in dev.items():
            if k == "command_results":
                dr.command_results = [
                    CommandResult(**{
                        "check_id": cr.get("check_id", ""),
                        "category": cr.get("category", "health"),
                        "command_key": cr.get("command_key", ""),
                        **{
                            fk: cr.get(fk)
                            for fk in ("command", "ok", "output_snippet",
                                      "artifact_id", "elapsed_ms",
                                      "error", "parsed_metric")
                        },
                    })
                    for cr in dev.get("command_results", []) or []
                ]
            elif k == "findings":
                dr.findings = [
                    Finding(**{
                        "finding_id": f.get("finding_id", f"fdg_{uuid.uuid4().hex[:10]}"),
                        "severity": f.get("severity", "info"),
                        **{
                            fk: f.get(fk)
                            for fk in ("title", "detail", "evidence",
                                       "asset_id", "check_id")
                        },
                    })
                    for f in dev.get("findings", []) or []
                ]
            elif k in _dr_known:
                setattr(dr, k, v)
            else:
                _unknown_seen.add(k)
        devices[aid] = dr
    if _unknown_seen:
        logger.warning(
            "_task_from_dict: dropped unknown DeviceResult fields: %s",
            sorted(_unknown_seen),
        )
    t = InspectionTask(
        task_id=d.get("task_id", ""),
        workspace_id=d.get("workspace_id", ""),
        scope=scope,
        profile_id=d.get("profile_id", ""),
        profile_display_name=d.get("profile_display_name", ""),
        status=d.get("status", "pending"),
        started_at=d.get("started_at", ""),
        finished_at=d.get("finished_at", ""),
        duration_ms=int(d.get("duration_ms") or 0),
        total_assets=d.get("total_assets", 0),
        succeeded=d.get("succeeded", 0),
        failed=d.get("failed", 0),
        skipped=d.get("skipped", 0),
        partial=d.get("partial", 0),
        warnings=d.get("warnings", 0),
        criticals=d.get("criticals", 0),
        infos=d.get("infos", 0),
        created_by=d.get("created_by", ""),
        session_id=d.get("session_id", ""),
        max_concurrency=d.get("max_concurrency", 3),
        cancel_requested_at=d.get("cancel_requested_at", ""),
        tracking=dict(d.get("tracking") or {}),
        devices=devices,
        error=d.get("error", ""),
    )
    ensure_tracking(t, source="load")
    return t


logger = logging.getLogger("agent.modules.inspection.runner")


# ── helper: asset metadata (read-only) ─────────────────────────────────────

def _get_asset_meta(workspace_id: str, asset_id: str) -> dict | None:
    """Resolve asset via ``ToolRuntimeClient.invoke("device.manage")``.

    We use the safe-by-default asset fetch (``action=get``) — the
    password field is not on the safe-by-default asset shape, so it
    never reaches us here. Password resolution happens server-side
    inside the canonical exec.run handler via asset_id.
    """
    client = get_default_tool_runtime_client()
    ctx = ToolRuntimeContext(
        workspace_id=workspace_id,
        requested_by=INSPECTION_CALLER,
        dry_run_default=False,
    )
    try:
        result = client.invoke(
            "device.manage",
            {"action": "get", "asset_id": asset_id, "workspace_id": workspace_id},
            context=ctx,
        )
    except Exception as exc:  # canonical runtime returns ToolResult; this is belt-and-braces
        return None
    if not hasattr(result, "status") or getattr(result, "status", "") == "blocked":
        return None
    output = getattr(result, "output", None) or {}
    if not isinstance(output, dict):
        return None
    asset = output.get("asset") if isinstance(output, dict) else None
    if not asset:
        # Some dispatchers return as plain dict or shape with 'assets'
        if isinstance(output, dict) and output.get("ok") and "asset" in output:
            asset = output["asset"]
        else:
            return None
    return asset


# ── helper: exec one command via canonical exec.run ──────────────────────

def _parse_tool_result(result) -> dict:
    """Translate a ``ToolResult`` (canonical exec.run) into the
    runner's internal ``{ok, output, error, session_id}`` shape.

    The earlier implementation only used ``result.ok`` (which doesn't
    exist on ``ToolResult`` — it has ``status``). That bug made every
    successful exec.run look like a 22s timeout. See commit bdae1cf.
    """
    status = str(getattr(result, "status", "") or "")
    if status == "blocked":
        return {
            "ok": False,
            "output": "",
            "error": "exec_run_blocked: "
                + (str(getattr(result, "summary", "") or "")[:200]),
        }
    if status != "succeeded":
        errors = list(getattr(result, "errors", []) or [])
        summary = str(getattr(result, "summary", "") or "")
        out = getattr(result, "output", None) or {}
        out_err = ""
        if isinstance(out, dict):
            out_err = str(out.get("error", "") or "")
        return {
            "ok": False,
            "output": "",
            "error": errors[0] if errors else (out_err or summary or "execution_failed"),
        }
    output = getattr(result, "output", None) or ""
    inner_ok, inner_output, inner_err = True, "", ""
    session_id = ""
    if isinstance(output, dict):
        inner_ok = bool(output.get("ok", True))
        inner_output = str(output.get("output", "") or "")
        inner_err = str(output.get("error", "") or "")
        session_id = str(output.get("session_id", "") or "")
    else:
        inner_output = str(output) if output else ""
    if not inner_ok:
        return {
            "ok": False,
            "output": inner_output,
            "error": inner_err or "execution_failed",
            "session_id": session_id,
        }
    return {"ok": True, "output": inner_output, "error": "", "session_id": session_id}


def _exec_one_command(workspace_id: str, asset_id: str, protocol: str,
                      command: str, timeout: int,
                      session_id: str = "", *, batch: bool = False) -> dict:
    """Run a single read-only command through ``exec.run`` over SSH/Telnet.

    ``session_id`` (optional): if a previous call on the same asset
    returned a session_id, pass it back here to reuse the existing
    SSH channel — the canonical ``_handler_network_ssh`` reuses
    ``get_session(session_id)`` instead of opening a fresh one.
    v3.9.14: per-asset session reuse cuts a 6-check run from 132s
    to ~30s by avoiding 5 redundant SSH connects.
    v4.2: ``batch=True`` sends all commands at once and reads full output.

    Returns a dict-shaped result (not ToolResult) so the runner can
    consume it directly. Network/protocol resolution is up to
    ``exec.run`` based on the asset's ``protocol`` (SSH or Telnet).
    The runner passes only ``asset_id`` + ``command``; credentials
    stay server-side.
    """
    client = get_default_tool_runtime_client()
    ctx = ToolRuntimeContext(
        workspace_id=workspace_id,
        requested_by=INSPECTION_CALLER,
        dry_run_default=False,
    )
    target = "telnet" if (protocol or "").lower() == "telnet" else "ssh"
    inv_args = {
        "action": "shell",
        "target": target,
        "asset_id": asset_id,
        "command": command,
        "workspace_id": workspace_id,
        "timeout": int(timeout),
    }
    if session_id:
        inv_args["session_id"] = session_id
    if batch:
        inv_args["batch"] = True
    # v3.10: surface the inspection call to the audit trail with
    # caller = INSPECTION_CALLER + asset + command key. The canonical
    # runtime records the call regardless; this logger entry
    # connects it back to the inspection task for the operator
    # reading logs.
    logger.info(
        "[inspection exec] ws=%s asset=%s protocol=%s cmd_key=%s timeout=%ds",
        workspace_id, asset_id, target, getattr(__import__("threading").current_thread(), "_inspection_cmd_key", ""), int(timeout),
    )
    try:
        result = client.invoke("exec.run", inv_args, context=ctx)
    except Exception as exc:
        return {"ok": False, "error": f"exec_runtime_error: {str(exc)[:200]}", "output": "", "session_id": ""}
    parsed = _parse_tool_result(result)
    parsed.setdefault("session_id", "")
    return parsed


def _close_remote_session(workspace_id: str, protocol: str, session_id: str) -> None:
    """Close a reused SSH/Telnet session through the canonical runtime."""
    if not session_id:
        return
    client = get_default_tool_runtime_client()
    ctx = ToolRuntimeContext(
        workspace_id=workspace_id,
        requested_by=INSPECTION_CALLER,
        dry_run_default=False,
    )
    target = "telnet" if (protocol or "").lower() == "telnet" else "ssh"
    try:
        client.invoke(
            "exec.run",
            {
                "action": "shell",
                "target": target,
                "session_id": session_id,
                "close_session": True,
                "workspace_id": workspace_id,
            },
            context=ctx,
        )
    except Exception:
        logger.debug("inspection: close remote session failed", exc_info=True)


def _close_registered_remote_sessions(workspace_id: str, task_id: str) -> None:
    """Best-effort hardening for cancel: close known task sessions now."""
    sessions = _registered_task_sessions(workspace_id, task_id)
    for session_id, protocol in sessions.items():
        _close_remote_session(workspace_id, protocol, session_id)
        _forget_task_session(workspace_id, task_id, session_id)


# ── one asset's checks ───────────────────────────────────────────────────


def _run_checks_on_asset(task: InspectionTask,
                         profile: InspectionProfile,
                         asset_meta: dict,
                         workspace_id: str) -> DeviceResult:
    """v4.0: flat command-list execution with pre/post commands.

    No more command_key lookups — the vendor profile carries an
    ordered list of raw commands.  LLM analyses the raw output
    directly so the runner doesn't parse or classify findings.
    """
    asset_id = str(asset_meta.get("asset_id") or "")
    dr = DeviceResult(task_id=task.task_id, asset_id=asset_id)
    if not asset_id:
        dr.status = "failed"
        dr.supported = False
        dr.errors.append("asset_id_missing")
        dr.finished_at = now_iso()
        return dr
    dr.asset_name = asset_meta.get("name", "")
    dr.host = asset_meta.get("host", "")
    dr.region = asset_meta.get("region") or ""
    dr.location = asset_meta.get("location") or ""
    dr.vendor = (asset_meta.get("vendor") or "").lower()
    dr.type = (asset_meta.get("type") or "").lower()
    dr.protocol = (asset_meta.get("protocol") or "ssh").lower()
    dr.status = "running"
    dr.started_at = now_iso()

    protocol = dr.protocol
    if protocol not in {"ssh", "telnet"}:
        dr.supported = False
        dr.limited_support = False
        dr.status = "skipped"
        dr.errors.append(f"protocol {protocol!r} is not supported by inspection (only ssh/telnet)")
        dr.finished_at = now_iso()
        return dr

    is_log = profile.profile_id == "log"

    vendor_profile = load_command_profile(workspace_id, dr.vendor, dr.type, script_type="log" if is_log else "general")
    effective_profile = (
        resolve_auto_profile(dr.vendor, dr.type)
        if profile.profile_id == AUTO_PROFILE_ID
        else profile
    )
    dr.script_profile_id = vendor_profile.vendor
    dr.script_profile_name = effective_profile.display_name
    if vendor_profile.vendor == "generic":
        dr.limited_support = True

    # ── v4.1: commands from workspace overrides only ────────────────────
    # Both general and log inspection use vendor_profile.commands (which
    # comes from workspace script overrides).  No more built-in command
    # lists — script management is the sole source.
    raw_commands: list[str] = list(vendor_profile.commands)

    pre_commands = list(vendor_profile.pre_commands) if vendor_profile.pre_commands else []
    post_commands = list(vendor_profile.post_commands) if vendor_profile.post_commands else []

    # ── empty commands → skip ─────────────────────────────────────────
    if not raw_commands:
        dr.status = "skipped"
        ds = "log" if is_log else "general"
        dr.errors.append(
            f"no_{ds}_script: vendor={vendor_profile.vendor} — "
            "请在脚本管理中为该厂商配置巡检命令"
        )
        dr.finished_at = now_iso()
        return dr

    # ── safety gate ────────────────────────────────────────────────────
    for cmd in raw_commands + pre_commands + post_commands:
        if not is_read_only_command(cmd):
            dr.status = "failed"
            dr.errors.append(f"blocked_write_command: {cmd[:80]}")
            dr.finished_at = now_iso()
            return dr

    # ── per-asset session reuse ────────────────────────────────────────
    bucket_session_id = ""
    batch_output = ""
    all_outputs: list[dict] = []

    def run_one(cmd: str, timeout: int = 30) -> None:
        nonlocal bucket_session_id
        if bucket_session_id:
            _register_task_session(workspace_id, task.task_id, dr.protocol, bucket_session_id)
        try:
            run_result = _exec_one_command(
                workspace_id, asset_id, dr.protocol, cmd,
                timeout=timeout,
                session_id=bucket_session_id,
            )
            new_sid = run_result.get("session_id", "") or ""
            if new_sid:
                bucket_session_id = new_sid
                _register_task_session(workspace_id, task.task_id, dr.protocol, bucket_session_id)
        except Exception:
            pass

    try:
        # ── pre_commands (welcome-banner flush + screen-length disable) ──
        for cmd in pre_commands:
            if _cancel_requested(workspace_id, task.task_id):
                break
            run_one(cmd, timeout=5)

        # ── v4.2: batch — send all commands at once ─────────────────
        if not _cancel_requested(workspace_id, task.task_id) and raw_commands:
            t0 = time.time()
            batch_payload = "\n".join(raw_commands) + "\n"
            try:
                run_result = _exec_one_command(
                    workspace_id, asset_id, dr.protocol, batch_payload,
                    timeout=max(60, len(raw_commands) * 5),
                    session_id=bucket_session_id, batch=True,
                )
            except Exception as exc:
                run_result = {
                    "ok": False, "output": "",
                    "error": f"batch_failed: {type(exc).__name__}: {str(exc)[:160]}",
                    "session_id": bucket_session_id,
                }
            elapsed = int((time.time() - t0) * 1000)
            new_sid = run_result.get("session_id", "") or ""
            if new_sid:
                bucket_session_id = new_sid
                _register_task_session(workspace_id, task.task_id, dr.protocol, bucket_session_id)
            batch_output = run_result.get("output", "") if run_result.get("ok") else ""
            all_outputs.append({
                "command": "batch",
                "ok": bool(run_result.get("ok")),
                "output": batch_output,
                "error": run_result.get("error", ""),
                "elapsed_ms": elapsed,
                "session_id": bucket_session_id,
            })

        # ── post_commands (undo screen-length disable) ──────────────────
        for cmd in post_commands:
            run_one(cmd, timeout=5)

    finally:
        _close_remote_session(workspace_id, dr.protocol, bucket_session_id)
        _forget_task_session(workspace_id, task.task_id, bucket_session_id)

    # ── populate CommandResult list ─────────────────────────────────────
    for i, rec in enumerate(all_outputs):
        cmd = rec["command"]
        ok = rec["ok"]
        is_batch = cmd == "batch"
        max_snippet = 15000 if is_batch else 2000
        snippet = redact_string(str(rec["output"])[:max_snippet]) if rec["output"] else ""
        cr = CommandResult(
            check_id=f"cmd_{i:03d}",
            category="raw",
            command_key="",
            command=cmd,
            ok=ok,
            output_snippet=snippet,
            elapsed_ms=rec["elapsed_ms"],
            error=rec.get("error", "") if not ok else "",
        )
        # Raw output saved as artifact for LLM consumption
        if ok and rec["output"]:
            art = save_artifact(
                workspace_id=workspace_id,
                content=rec["output"],
                artifact_type="inspection_raw",
                title=f"{dr.asset_name or asset_id} — 巡检输出",
                sensitivity="sensitive",
                run_id=task.task_id,
                capability_id="inspection",
                metadata={
                    "inspection_task_id": task.task_id,
                    "asset_id": asset_id,
                    "command_count": len(raw_commands) if is_batch else 1,
                    "index": i,
                },
            )
            if art is not None:
                cr.artifact_id = getattr(art, "artifact_id", "")
        dr.command_results.append(cr)

    # Status
    dr.finished_at = now_iso()
    if all_outputs:
        ok_count = sum(1 for r in all_outputs if r["ok"])
        if ok_count == len(all_outputs):
            dr.status = "succeeded"
        elif ok_count > 0:
            dr.status = "partial"
        else:
            dr.status = "failed"
    else:
        dr.status = "skipped"
    return dr




# ── top-level runner ───────────────────────────────────────────────────

def _resolve_target_assets(scope: InspectionScope, workspace_id: str) -> list[dict]:
    """Resolve the scope against CMDB. Returns a list of asset dicts.

    When ``asset_ids`` are provided, only those assets are returned.
    When filters (region/type/vendor/location/protocol/search/tags)
    are provided, those are applied to the CMDB list.

    **Safety gate**: if *no* criteria are specified at all — no
    asset_ids, no region, no type, no vendor, no location, no
    protocol, no search, no tags — the function returns an empty
    list instead of sweeping every asset.  An inspection with no
    target is almost certainly a caller bug (e.g. LLM forgot to
    pass the scope parameter); silently running against the entire
    fleet would be surprising and destructive.
    """
    from agent.modules.cmdb.service import list_assets
    if scope.asset_ids:
        all_assets = list_assets(workspace_id, filter={})
        by_id = {str(a.get("asset_id") or ""): a for a in all_assets}
        assets = [by_id[aid] for aid in scope.asset_ids if aid in by_id]
        missing = set(scope.asset_ids) - set(by_id)
        if missing:
            for mid in missing:
                logger.info(
                    "inspection: explicit asset_id %s not found in CMDB", mid,
                )
    elif scope.is_empty():
        # Safety gate — no criteria at all means the caller almost
        # certainly forgot to pass a scope.  Return empty instead of
        # silently sweeping the entire CMDB.
        logger.warning(
            "inspection: empty scope — no asset_ids and no filters. "
            "Refusing to sweep all assets. Is the caller missing a scope parameter?"
        )
        return []
    else:
        f: dict[str, str] = {}
        if scope.region:
            f["region"] = scope.region
        if scope.type:
            f["type"] = scope.type
        if scope.vendor:
            f["vendor"] = scope.vendor
        if scope.location:
            f["location"] = scope.location
        if scope.protocol:
            f["protocol"] = scope.protocol
        assets = list_assets(workspace_id, filter=f)
        if scope.search:
            q = str(scope.search or "").strip().lower()
            if q:
                assets = [
                    a for a in assets
                    if q in " ".join(str(a.get(k, "") or "") for k in (
                        "asset_id", "name", "host", "vendor", "model",
                        "region", "location", "type",
                    )).lower()
                ]
        if scope.tags:
            wanted = {t.strip() for t in scope.tags if t.strip()}
            assets = [
                a for a in assets
                if wanted.issubset({t.strip() for t in (a.get("tags") or [])})
            ]
    if scope.limit and len(assets) > scope.limit:
        assets = assets[: scope.limit]
    return assets


def run_task(workspace_id: str,
             profile_id: str,
             scope: InspectionScope,
             *,
             created_by: str = "user",
             session_id: str = "",
             max_concurrency: int = 3,
             task_id: str = "") -> InspectionTask:
    """Run an inspection synchronously and return the populated task.

    MVP: synchronous. Errors per device are isolated — one bad
    SSH target never affects another asset's results.
    """
    profile_id = str(profile_id or "").strip() or AUTO_PROFILE_ID
    profile = resolve_profile(profile_id)
    if profile is None:
        # Surface the unknown profile as an empty failed task so
        # the API can communicate the error back consistently.
        started = now_iso()
        bad = InspectionTask(
            task_id=str(task_id or "").strip() or _new_task_id(),
            workspace_id=workspace_id,
            scope=scope,
            profile_id=profile_id,
            profile_display_name="",
            status="failed",
            created_by=created_by,
            session_id=session_id,
            max_concurrency=max_concurrency,
            started_at=started,
            finished_at=started,  # zero-duration, not crashed
            error=(
                f"unknown_profile: {profile_id}. "
                f"Available: {sorted(BUILTIN_PROFILES.keys())}."
            ),
        )
        bad.duration_ms = 0
        _save_task(workspace_id, bad)
        return bad

    target_assets = _resolve_target_assets(scope, workspace_id)

    task = InspectionTask(
        task_id=str(task_id or "").strip() or _new_task_id(),
        workspace_id=workspace_id,
        scope=scope,
        profile_id=profile.profile_id,
        profile_display_name=profile.display_name,
        status="running",
        created_by=created_by,
        session_id=session_id,
        max_concurrency=max_concurrency,
    )
    task.total_assets = len(target_assets)
    task.started_at = now_iso()
    ensure_tracking(task, source="run")
    _save_task(workspace_id, task)

    if not target_assets:
        task.status = "failed"
        task.error = "no_assets_matched_scope"
        task.finished_at = now_iso()
        ensure_tracking(task, source="run")
        _save_task(workspace_id, task)
        return task

    # Concurrency control. Each device's checks run serially inside
    # its worker; the pool only parallelises across devices. When
    # there's only one device (or max_concurrency == 1) we skip the
    # pool entirely — the per-task save lock would block on a single
    # worker, the executor adds no value, and the cancel-poll
    # machinery is the same.
    max_workers = max(1, min(max_concurrency, len(target_assets)))
    outcomes: dict[str, DeviceResult] = {}
    cancelled = False
    cancel_marker = ""

    def _record_device(dr: DeviceResult) -> None:
        """Idempotent per-device merge + progress save.

        v3.10 (inspection): collapses the read-modify-write window
        for ``task.devices`` so concurrent device workers can't
        write a stale view. ``_save_task`` also takes the per-task
        save lock; the two together guarantee progress is monotonic.

        v3.11: Also incrementally updates the task-level counters so
        the frontend progress card shows live numbers, not just 0%.
        All mutations (dict + counters) happen under the lock to avoid
        a read/write race between concurrent device workers.
        """
        with _get_task_save_lock(task.task_id):
            outcomes[dr.asset_id] = dr
            task.devices = dict(outcomes)
            # Incrementally update counters for live progress display
            task.succeeded = sum(1 for d in outcomes.values() if d.status == "succeeded")
            task.failed    = sum(1 for d in outcomes.values() if d.status == "failed")
            task.partial   = sum(1 for d in outcomes.values() if d.status == "partial")
            task.skipped   = sum(1 for d in outcomes.values() if d.status == "skipped")
            # v4.0: findings not generated — keep at 0
            _save_task_unlocked(workspace_id, task)

    def _run_one_serial(asset_meta: dict) -> DeviceResult:
        try:
            return _run_one_device_with_meta(
                workspace_id, asset_meta, task, profile,
            )
        except Exception as exc:
            aid = str(asset_meta.get("asset_id") or "")
            dr = DeviceResult(task_id=task.task_id, asset_id=aid)
            dr.status = "failed"
            dr.supported = False
            dr.errors.append(
                f"runner_internal_error: {type(exc).__name__}: {str(exc)[:200]}"
            )
            dr.finished_at = now_iso()
            return dr

    try:
        if max_workers == 1:
            # Single device: sequential. Each device finishes,
            # records, and we check cancel between devices (per-check
            # cancel still happens inside the device worker).
            for asset_meta in target_assets:
                if _cancel_requested(workspace_id, task.task_id) and not cancel_marker:
                    cancel_marker = _consume_cancel_marker(workspace_id, task.task_id)
                    cancelled = True
                    dr = DeviceResult(
                        task_id=task.task_id,
                        asset_id=str(asset_meta.get("asset_id") or ""),
                    )
                    dr.status = "skipped"
                    dr.errors.append("cancelled_before_dispatch")
                    dr.finished_at = now_iso()
                    _record_device(dr)
                    continue
                dr = _run_one_serial(asset_meta)
                _record_device(dr)
        else:
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                futures = {
                    ex.submit(
                        _run_one_device_with_meta,
                        workspace_id, asset_meta, task, profile,
                    ): asset_meta["asset_id"]
                    for asset_meta in target_assets
                }
                handled: set = set()
                for fut in as_completed(futures):
                    try:
                        dr = fut.result()
                    except Exception as exc:
                        aid = futures[fut]
                        dr = DeviceResult(task_id=task.task_id, asset_id=aid)
                        dr.status = "failed"
                        dr.supported = False
                        dr.errors.append(
                            f"runner_internal_error: {str(exc)[:200]}"
                        )
                        dr.finished_at = now_iso()
                    _record_device(dr)
                    handled.add(fut)
                    if _cancel_requested(workspace_id, task.task_id) and not cancel_marker:
                        cancel_marker = _consume_cancel_marker(workspace_id, task.task_id)
                        cancelled = True
                        # Record the completed future we just observed,
                        # then stop queued futures that haven't started.
                        for other in futures:
                            if other not in handled:
                                try:
                                    other.cancel()
                                except Exception:
                                    logger.debug(
                                        "inspection: future.cancel failed",
                                        exc_info=True,
                                    )
                        break
                # Drain already-submitted futures so we don't leak
                # threads. Workers stop as soon as their device
                # completes (the cancel poll lives inside the
                # per-check loop). Cancelled futures are recorded as
                # skipped so the operator can see they were not run.
                for fut in futures:
                    if fut in handled:
                        continue
                    aid = futures[fut]
                    if getattr(fut, "cancelled", lambda: False)():
                        dr = DeviceResult(task_id=task.task_id, asset_id=aid)
                        dr.status = "skipped"
                        dr.errors.append("cancelled_before_dispatch")
                        dr.finished_at = now_iso()
                        _record_device(dr)
                        handled.add(fut)
                        continue
                    try:
                        dr = fut.result()
                    except Exception as exc:
                        dr = DeviceResult(task_id=task.task_id, asset_id=aid)
                        dr.status = "failed"
                        dr.supported = False
                        dr.errors.append(
                            f"runner_internal_error: {str(exc)[:200]}"
                        )
                        dr.finished_at = now_iso()
                    if dr.asset_id not in outcomes:
                        _record_device(dr)
                    handled.add(fut)
    except Exception as exc:
        # v3.9.14: if the executor blew up (e.g. resource exhaustion),
        # we still persist whatever we have so the task does NOT stay
        # #4/#6 phantom-running on disk.
        task.error = f"runner_internal: {type(exc).__name__}: {str(exc)[:160]}"
        logger.exception("inspection: run_task executor crashed")

    # Finalize: _record_device() already keeps counters accurate via sum(),
    # so task.succeeded/failed/partial/skipped are already correct here.
    # Do NOT re-accumulate — that would double the counts.
    task.devices = outcomes
    # v4.0: findings are not generated — LLM does the analysis.
    # Keep counters at 0; the progress card still shows device-level stats.

    # Status roll-up at task level. Cancel precedence: if the user
    # asked to stop, the task is cancelled (we keep any succeeded
    # devices in outcomes for the report). Otherwise fall through to
    # succeeded / partial / failed.
    if cancelled:
        task.status = "partial" if task.succeeded > 0 else "cancelled"
        if cancel_marker:
            task.cancel_requested_at = cancel_marker
    elif task.failed == 0 and task.partial == 0 and task.skipped == 0:
        task.status = "succeeded"
    elif task.failed == 0 and (task.succeeded > 0 or task.partial > 0):
        task.status = "partial"
    elif task.succeeded > 0 or task.partial > 0:
        task.status = "partial"
    else:
        task.status = "failed"
    task.finished_at = now_iso()
    ensure_tracking(task, source="run")
    try:
        _save_task(workspace_id, task)
    finally:
        _release_task_save_lock(task.task_id)
    return task


def _run_one_device_with_meta(workspace_id: str, asset_meta: dict,
                               task: InspectionTask,
                               profile: InspectionProfile) -> DeviceResult:
    asset_id = str(asset_meta.get("asset_id") or "")
    resolved = _get_asset_meta(workspace_id, asset_id) if asset_id else None
    if not resolved:
        dr = DeviceResult(task_id=task.task_id, asset_id=asset_id)
        dr.asset_name = str(asset_meta.get("name") or "")
        dr.host = str(asset_meta.get("host") or "")
        dr.status = "failed"
        dr.supported = False
        dr.errors.append(f"asset_not_found: {asset_id}" if asset_id else "asset_id_missing")
        dr.finished_at = now_iso()
        return dr
    dr = _run_checks_on_asset(task, profile, resolved, workspace_id)
    return dr


def _new_task_id() -> str:
    return f"ins_{uuid.uuid4().hex[:12]}"


def create_pending_task(workspace_id: str,
                        profile_id: str,
                        scope: InspectionScope,
                        *,
                        created_by: str = "user",
                        session_id: str = "",
                        max_concurrency: int = 3,
                        task_id: str = "") -> InspectionTask:
    """Create and persist a real pending task before async execution.

    HTTP ``async_run`` needs a real task id immediately so the
    frontend can poll and cancel the same task the background worker
    will execute. This function performs the cheap validation and
    CMDB scope resolution up front, persists the task, and leaves
    actual device execution to ``run_task(..., task_id=...)``.
    """
    profile_id = str(profile_id or "").strip() or AUTO_PROFILE_ID
    profile = resolve_profile(profile_id)
    task_id = str(task_id or "").strip() or _new_task_id()
    started = now_iso()
    if profile is None:
        bad = InspectionTask(
            task_id=task_id,
            workspace_id=workspace_id,
            scope=scope,
            profile_id=profile_id,
            profile_display_name="",
            status="failed",
            created_by=created_by,
            session_id=session_id,
            max_concurrency=max_concurrency,
            started_at=started,
            finished_at=started,
            error=(
                f"unknown_profile: {profile_id}. "
                f"Available: {sorted(BUILTIN_PROFILES.keys())}."
            ),
        )
        _save_task(workspace_id, bad)
        return bad

    target_assets = _resolve_target_assets(scope, workspace_id)
    task = InspectionTask(
        task_id=task_id,
        workspace_id=workspace_id,
        scope=scope,
        profile_id=profile.profile_id,
        profile_display_name=profile.display_name,
        status="pending",
        created_by=created_by,
        session_id=session_id,
        max_concurrency=max_concurrency,
        total_assets=len(target_assets),
        started_at=started,
    )
    if not target_assets:
        task.status = "failed"
        task.error = "no_assets_matched_scope"
        task.finished_at = started
    ensure_tracking(task, source="pending")
    _save_task(workspace_id, task)
    return task


def cancel_task(workspace_id: str, task_id: str) -> dict:
    """Mark a task for cooperative cancellation.

    The runner is a thread pool; we can't yank the rug out. Setting the
    cancel marker tells the per-asset loop to stop dispatching new
    checks after the current one completes. Final ``status`` flips
    to ``cancelled`` (only ``partial`` if some devices finished).
    """
    t = load_task(workspace_id, task_id)
    if t is None:
        return {"ok": False, "error": "task_not_found"}
    if t.status in ("succeeded", "failed", "cancelled", "partial"):
        return {"ok": False, "error": f"task_already_{t.status}"}
    marker = now_iso()
    with _CANCEL_LOCK:
        _CANCEL_REQUESTS[(workspace_id, task_id)] = marker
    _close_registered_remote_sessions(workspace_id, task_id)
    # Persist the marker on the task record so a backend restart
    # between mark and run still honours the cancel.
    t.cancel_requested_at = marker
    _save_task(workspace_id, t)
    return {
        "ok": True,
        "supported": True,
        "task_id": task_id,
        "marked_at": marker,
        "note": "in-flight checks finish; remaining assets skipped",
    }
