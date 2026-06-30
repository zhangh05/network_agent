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

The runner is async-by-design (returns when done) but synchronous
in the MVP; the service layer offloads to a thread pool when
``max_concurrency > 1``.
"""

from __future__ import annotations

import logging
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from agent.runtime.utils import now_iso, from_iso, duration_ms
from artifacts.store import save_artifact
from tool_runtime.redaction import redact_string
from tool_runtime.context import ToolRuntimeContext
from tool_runtime.integration import get_default_tool_runtime_client
from tool_runtime.schemas import ToolInvocation

from .models import (
    CommandResult,
    DeviceResult,
    Finding,
    InspectionProfile,
    InspectionScope,
    InspectionTask,
)
from .parser import run_parser, parse_current_config
from .profiles import (
    BUILTIN_PROFILES,
    CK_CURRENT_CONFIG,
    CK_VERSION,
    AUTO_PROFILE_ID,
    resolve_auto_profile,
    resolve_profile,
    resolve_command_profile,
    is_read_only_command,
)


# v3.10 (inspection): caller identifier for the canonical
# ToolRuntimeClient. The exec.run and device.manage manifests are
# extended with this caller.
INSPECTION_CALLER = "inspection_runner"


# ── storage ──────────────────────────────────────────────────────────────

def _inspection_root(workspace_id: str):
    from workspace.run_store import WS_ROOT
    from workspace.ids import validate_workspace_id
    return WS_ROOT / validate_workspace_id(workspace_id) / "inspection"


def _task_path(workspace_id: str, task_id: str):
    return _inspection_root(workspace_id) / "tasks" / f"{task_id}.json"


def _save_task(workspace_id: str, task: InspectionTask) -> None:
    from workspace.atomic_io import atomic_write_json
    p = _task_path(workspace_id, task.task_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    # dataclasses → dict
    from dataclasses import asdict
    atomic_write_json(p, asdict(task))


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


def _task_from_dict(d: dict) -> InspectionTask:
    """Construct InspectionTask from a serialized dict.

    Dataclass field-name round-trip via InspectionScope / DeviceResult
    construction; nested device.results round-trip via dict and model
    rebuild keeps the on-disk shape simple.
    """
    scope_raw = d.get("scope", {}) or {}
    scope = InspectionScope(
        region=scope_raw.get("region", ""),
        location=scope_raw.get("location", ""),
        type=scope_raw.get("type", ""),
        vendor=scope_raw.get("vendor", ""),
        tags=tuple(scope_raw.get("tags", []) or []),
        asset_ids=tuple(scope_raw.get("asset_ids", []) or []),
        limit=scope_raw.get("limit", 50),
    )
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
            else:
                setattr(dr, k, v)
        devices[aid] = dr
    t = InspectionTask(
        task_id=d.get("task_id", ""),
        workspace_id=d.get("workspace_id", ""),
        scope=scope,
        profile_id=d.get("profile_id", ""),
        profile_display_name=d.get("profile_display_name", ""),
        status=d.get("status", "pending"),
        started_at=d.get("started_at", ""),
        finished_at=d.get("finished_at", ""),
        total_assets=d.get("total_assets", 0),
        succeeded=d.get("succeeded", 0),
        failed=d.get("failed", 0),
        skipped=d.get("skipped", 0),
        warnings=d.get("warnings", 0),
        criticals=d.get("criticals", 0),
        infos=d.get("infos", 0),
        created_by=d.get("created_by", ""),
        session_id=d.get("session_id", ""),
        max_concurrency=d.get("max_concurrency", 3),
        devices=devices,
        error=d.get("error", ""),
    )
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
    if getattr(result, "status", "") == "blocked":
        return None
    output = getattr(result, "output", None) or {}
    asset = output.get("asset") if isinstance(output, dict) else None
    if not asset:
        # Some dispatchers return as plain dict or shape with 'assets'
        if isinstance(output, dict) and output.get("ok") and "asset" in output:
            asset = output["asset"]
        else:
            return None
    return asset


# ── helper: exec one command via canonical exec.run ──────────────────────

def _exec_one_command(workspace_id: str, asset_id: str, protocol: str,
                      command: str, timeout: int) -> dict:
    """Run a single read-only command through ``exec.run`` over SSH/Telnet.

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
    try:
        result = client.invoke("exec.run", inv_args, context=ctx)
    except Exception as exc:
        return {"ok": False, "error": f"exec_runtime_error: {str(exc)[:200]}", "output": ""}

    # v3.9.14: ToolResult has ``status`` (succeeded|failed|blocked|dry_run),
    # NOT ``ok``. The earlier ``result.ok`` lookup always returned False
    # because the attribute is missing — every successful exec.run was
    # being reported as a 22-second timeout to the runner.
    status = str(getattr(result, "status", "") or "")
    if status == "blocked":
        return {
            "ok": False,
            "output": "",
            "error": "exec_run_blocked: "
                + (str(getattr(result, "summary", "") or "")[:200]),
        }
    if status != "succeeded":
        # Status strings differ — prefer explicit error path
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
    # exec.run actual handler returns dict; for the canonical ``exec.run``
    # shell path we expect {"ok": ..., "output": ..., ...}. Surface fields:
    inner_ok, inner_output, inner_err = True, "", ""
    if isinstance(output, dict):
        inner_ok = bool(output.get("ok", True))
        inner_output = str(output.get("output", "") or "")
        inner_err = str(output.get("error", "") or "")
    else:
        inner_output = str(output) if output else ""
    if not inner_ok:
        return {"ok": False, "output": inner_output, "error": inner_err or "execution_failed"}
    return {"ok": True, "output": inner_output, "error": ""}


# ── one asset's checks ───────────────────────────────────────────────────

def _run_checks_on_asset(task: InspectionTask,
                         profile: InspectionProfile,
                         asset_meta: dict,
                         workspace_id: str) -> DeviceResult:
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
        # HTTPS / SNMP assets are kept out of inspection for now;
        # this is a real-supported-yes command catalogue limitation,
        # not a silent skip.
        dr.supported = False
        dr.limited_support = False
        dr.status = "skipped"
        dr.errors.append(f"protocol {protocol!r} is not supported by inspection (only ssh/telnet)")
        dr.finished_at = now_iso()
        return dr

    vendor_profile = resolve_command_profile(dr.vendor, dr.type)
    effective_profile = (
        resolve_auto_profile(dr.vendor, dr.type)
        if profile.profile_id == AUTO_PROFILE_ID
        else profile
    )
    dr.script_profile_id = vendor_profile.vendor
    dr.script_profile_name = effective_profile.display_name
    if vendor_profile.vendor == "generic":
        # Only if the asset's vendor doesn't have a profile we mark
        # ``limited_support``; the runner will still try the safe
        # subset (version + interface brief) for any device so the
        # report is never totally blank.
        dr.limited_support = True

    # Sort checks deterministically (task_id prefix keeps order stable)
    checks = list(effective_profile.checks)
    checks.sort(key=lambda c: c.check_id)

    config_check_seen = False
    for check in checks:
        cmd_key = check.command_key
        if cmd_key not in vendor_profile.commands:
            dr.command_results.append(CommandResult(
                check_id=check.check_id,
                category=check.category,
                command_key=cmd_key,
                command="",
                ok=False,
                error=f"vendor {dr.vendor or 'unknown'} does not support check {cmd_key!r}",
            ))
            continue

        command = vendor_profile.commands[cmd_key]
        if not is_read_only_command(command):
            cr = CommandResult(
                check_id=check.check_id,
                category=check.category,
                command_key=cmd_key,
                command=command,
                ok=False,
                error="command failed static read-only check",
            )
            dr.command_results.append(cr)
            dr.errors.append(
                f"refused to run non-read-only command at check {check.check_id}"
            )
            continue

        t0 = time.time()
        run_result = _exec_one_command(
            workspace_id, asset_id, dr.protocol, command,
            timeout=check.timeout_seconds,
        )
        elapsed = int((time.time() - t0) * 1000)
        output = run_result["output"]
        ok = run_result["ok"]

        # Persist raw output as an artifact (config backup reads
        # back the same artifact later in the task for diffing).
        artifact_id = ""
        snippet = redact_string(output[:800]) if output else ""
        if output and cmd_key == CK_CURRENT_CONFIG and ok:
            art = save_artifact(
                workspace_id=workspace_id,
                content=output,
                artifact_type="config_backup",
                title=f"{asset_meta.get('name') or asset_id} current-config",
                sensitivity="sensitive",
                run_id=task.task_id,
                capability_id="inspection",
                metadata={
                    "inspection_task_id": task.task_id,
                    "asset_id": asset_id,
                    "vendor": dr.vendor,
                    "command_key": cmd_key,
                },
            )
            if art is not None:
                artifact_id = getattr(art, "artifact_id", "")
            snippet = (
                "[current configuration saved as sensitive artifact"
                + (f" {artifact_id}" if artifact_id else "")
                + "]"
            )

        # Parser
        parser_kwargs: dict = {"asset_id": asset_id, "check_id": check.check_id}
        # For current_config we feed the previous-config snapshot
        # for diffing — this is the agent.user_circuit: each run of
        # the same asset config_backup will diff against the most
        # recent prior snapshot.
        if check.command_key == CK_CURRENT_CONFIG:
            prev = _latest_config_snapshot(workspace_id, asset_id, exclude_task_id=task.task_id)
            if prev:
                parser_kwargs["previous_output"] = prev.get("content", "")
            config_check_seen = True

        metric, findings = run_parser(
            check.parser_key or cmd_key,
            output,
            **parser_kwargs,
        )

        cr = CommandResult(
            check_id=check.check_id,
            category=check.category,
            command_key=cmd_key,
            command=command,
            ok=ok,
            output_snippet=snippet,
            artifact_id=artifact_id,
            elapsed_ms=elapsed,
            error=run_result.get("error", "") if not ok else "",
            parsed_metric=metric,
        )
        dr.command_results.append(cr)

        # Attach findings + count
        for f in findings:
            # Re-bind asset_id to the device's id (parser may have
            # been given the check_id alone); always pin to current asset.
            if not f.asset_id:
                f.asset_id = asset_id
            dr.findings.append(f)

    # Status roll-up
    dr.finished_at = now_iso()
    if any(not cr.ok for cr in dr.command_results):
        dr.status = "failed"
    elif dr.command_results and all(cr.ok for cr in dr.command_results):
        dr.status = "succeeded"
    elif not dr.command_results:
        dr.status = "skipped"
    return dr


def _latest_config_snapshot(workspace_id: str, asset_id: str, *,
                             exclude_task_id: str = "") -> dict | None:
    """Find the most recent prior current-config artifact for the asset.

    Bypass can_save_artifact indexes for the live write path; we
    scan on disk via the artifact records jsonl instead.
    """
    from workspace.ids import validate_workspace_id
    from workspace.run_store import WS_ROOT
    from workspace.atomic_io import safe_read_text
    p = (WS_ROOT / validate_workspace_id(workspace_id)
         / "index" / "artifacts.jsonl")
    if not p.is_file():
        return None
    try:
        text = safe_read_text(p, default="")
    except Exception:
        return None
    target_type = "config_backup"
    candidates: list[dict] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            rec = __import__("json").loads(line)
        except Exception:
            continue
        if rec.get("artifact_type") != target_type:
            continue
        meta = rec.get("metadata") or {}
        if meta.get("asset_id") != asset_id:
            continue
        if exclude_task_id and meta.get("inspection_task_id") == exclude_task_id:
            continue
        if meta.get("inspection_task_id") == exclude_task_id:
            continue
        candidates.append(rec)
    if not candidates:
        return None
    candidates.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    # Read the file payload (we keep the jsonl metadata only — actual
    # content lives under workspaces/<ws>/sys/.../<id>.txt).
    return _read_artifact_content(workspace_id, candidates[0])


def _read_artifact_content(workspace_id: str, rec: dict) -> dict | None:
    """Materialize an artifact record's ``content`` (best effort)."""
    if not rec:
        return None
    file_path = rec.get("file_path") or rec.get("path")
    if not file_path:
        return {"content": "", "metadata": rec}
    try:
        from pathlib import Path
        return {
            "content": Path(file_path).read_text(encoding="utf-8", errors="replace"),
            "metadata": rec,
        }
    except Exception:
        return {"content": "", "metadata": rec}


# ── top-level runner ───────────────────────────────────────────────────

def _resolve_target_assets(scope: InspectionScope, workspace_id: str) -> list[dict]:
    """Resolve the scope against CMDB. Returns a list of asset dicts."""
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
        assets = list_assets(workspace_id, filter=f)
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
             max_concurrency: int = 3) -> InspectionTask:
    """Run an inspection synchronously and return the populated task.

    MVP: synchronous. Errors per device are isolated — one bad
    SSH target never affects another asset's results.
    """
    profile_id = str(profile_id or "").strip() or AUTO_PROFILE_ID
    profile = resolve_profile(profile_id)
    if profile is None:
        # Surface the unknown profile as an empty failed task so
        # the API can communicate the error back consistently.
        bad = InspectionTask(
            task_id=_new_task_id(),
            workspace_id=workspace_id,
            scope=scope,
            profile_id=profile_id,
            profile_display_name="",
            status="failed",
            created_by=created_by,
            session_id=session_id,
            max_concurrency=max_concurrency,
            error=f"unknown_profile: {profile_id}",
        )
        bad.started_at = now_iso()
        bad.finished_at = now_iso()
        _save_task(workspace_id, bad)
        return bad

    target_assets = _resolve_target_assets(scope, workspace_id)

    task = InspectionTask(
        task_id=_new_task_id(),
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
    _save_task(workspace_id, task)

    if not target_assets:
        task.status = "succeeded"
        task.finished_at = now_iso()
        _save_task(workspace_id, task)
        return task

    # Concurrency control. Each device's checks run serially inside
    # its worker; the pool only parallelises across devices.
    max_workers = max(1, min(max_concurrency, len(target_assets)))
    outcomes: dict[str, DeviceResult] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {
            ex.submit(
                _run_one_device_with_meta,
                workspace_id, asset_meta, task, profile,
            ): asset_meta["asset_id"]
            for asset_meta in target_assets
        }
        for fut in as_completed(futures):
            try:
                dr = fut.result()
            except Exception as exc:
                aid = futures[fut]
                dr = DeviceResult(task_id=task.task_id, asset_id=aid)
                dr.status = "failed"
                dr.supported = False
                dr.errors.append(f"runner_internal_error: {str(exc)[:200]}")
                dr.finished_at = now_iso()
            outcomes[dr.asset_id] = dr

    # Finalize
    task.devices = outcomes
    for dr in outcomes.values():
        if dr.status == "succeeded":
            task.succeeded += 1
        elif dr.status == "skipped":
            task.skipped += 1
        else:
            task.failed += 1
        for f in dr.findings:
            if f.severity == "critical":
                task.criticals += 1
            elif f.severity == "warning":
                task.warnings += 1
            elif f.severity == "info":
                task.infos += 1

    if task.failed == 0:
        task.status = "succeeded"
    elif task.succeeded > 0:
        task.status = "partial"
    else:
        task.status = "failed"
    task.finished_at = now_iso()
    _save_task(workspace_id, task)
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


def cancel_task(workspace_id: str, task_id: str) -> dict:
    """MVP cancellation.

    The MVP runs synchronously, so a task that is ``running`` is
    already in-progress inside the orchestration. We do NOT silently
    mark it cancelled; we tell the caller the operation is
    unavailable for the synchronous path. Future async path
    will flip ``status`` to ``cancelled``.
    """
    t = load_task(workspace_id, task_id)
    if t is None:
        return {"ok": False, "error": "task_not_found", "supported": True}
    return {
        "ok": False,
        "error": "not_supported",
        "supported": False,
        "reason": "MVP runs inspection synchronously; cancellation is a no-op.",
        "task_id": task_id,
    }
