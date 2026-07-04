"""agent.modules.inspection.service

Backend-facing surface. The API routes in
``backend/api/inspection_routes.py`` call into here.

Public functions:
    list_profiles()
    create_task(workspace_id, profile_id, scope, ...) -> InspectionTask
    list_tasks(workspace_id, limit)
    get_task(workspace_id, task_id)
    cancel_task(workspace_id, task_id)
    render_report(workspace_id, task_id, format)
"""

from __future__ import annotations

from typing import Any, Optional

from agent.runtime.utils import now_iso
from workspace.ids import validate_workspace_id

from .models import InspectionScope, InspectionTask
from .profiles import BUILTIN_PROFILES, resolve_profile
from .runner import (
    INSPECTION_CALLER,
    cancel_task as _runner_cancel,
    create_pending_task as _runner_create_pending,
    list_tasks as _runner_list,
    load_task as _runner_load,
    record_tracking_poll as _runner_record_poll,
    run_task as _runner_run,
)
from .tracking import ensure_tracking
from . import report as _report


# ── validation ──────────────────────────────────────────────────────────

def _validate_workspace(workspace_id: str) -> str:
    ws = validate_workspace_id(workspace_id)
    return ws


def list_profiles() -> list[dict]:
    """Return all builtin profiles as plain dicts."""
    out: list[dict] = []
    for prof in BUILTIN_PROFILES.values():
        out.append({
            "profile_id": prof.profile_id,
            "display_name": prof.display_name,
            "description": prof.description,
            "risk_level": prof.risk_level,
            "requires_approval": prof.requires_approval,
            "checks": [
                {
                    "check_id": c.check_id,
                    "category": c.category,
                    "display_name": c.display_name,
                    "command_key": c.command_key,
                    "parser_key": c.parser_key,
                    "severity_default": c.severity_default,
                    "timeout_seconds": c.timeout_seconds,
                }
                for c in prof.checks
            ],
        })
    return out


def _tuple_of_strings(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        parts = value.replace("，", ",").split(",")
        return tuple(p.strip() for p in parts if p.strip())
    if isinstance(value, (list, tuple, set)):
        return tuple(str(v).strip() for v in value if str(v).strip())
    return ()


def _coerce_limit(value: Any, default: int = 50) -> int:
    try:
        limit = int(value if value not in (None, "") else default)
    except (TypeError, ValueError):
        limit = default
    return max(1, min(limit, 500))


def _coerce_scope(scope_in: dict | None) -> InspectionScope:
    s = scope_in or {}
    return InspectionScope(
        region=str(s.get("region", "") or ""),
        location=str(s.get("location", "") or ""),
        search=str(s.get("search", "") or ""),
        type=str(s.get("type", "") or ""),
        vendor=str(s.get("vendor", "") or ""),
        protocol=str(s.get("protocol", "") or ""),
        tags=_tuple_of_strings(s.get("tags")),
        asset_ids=_tuple_of_strings(s.get("asset_ids")),
        limit=_coerce_limit(s.get("limit", 50)),
    )


def create_task(workspace_id: str, profile_id: str, scope: dict | None = None,
                created_by: str = "user", session_id: str = "",
                max_concurrency: int = 3, task_id: str = "") -> InspectionTask:
    """Validate, then hand off to ``runner.run_task``.

    All required parameters are positional-or-keyword with explicit
    defaults so callers can't be tricked into passing ``workspace_id=None``.
    """
    ws = _validate_workspace(workspace_id)
    profile = resolve_profile(profile_id)
    if profile is None:
        # Surface as a failed InspectionTask so the API layer's
        # response shape is consistent.
        bad = InspectionTask(
            task_id="",
            workspace_id=ws,
            scope=_coerce_scope(scope),
            profile_id=profile_id,
            status="failed",
            created_by=created_by,
            session_id=session_id,
            max_concurrency=max_concurrency,
            error=f"unknown_profile: {profile_id}",
            started_at=now_iso(),
            finished_at=now_iso(),
        )
        return bad

    coerced_scope = _coerce_scope(scope)
    if max_concurrency < 1:
        max_concurrency = 1
    # v3.9.14 upper bound — beyond 16 devices in flight we hit SSH
    # session limits and the run gets slower than serial. Match the
    # route handler so behaviour is identical whether the caller
    # passes it via the API or directly.
    if max_concurrency > 16:
        max_concurrency = 16
    return _runner_run(
        workspace_id=ws,
        profile_id=profile_id,
        scope=coerced_scope,
        created_by=created_by,
        session_id=session_id,
        max_concurrency=max_concurrency,
        task_id=task_id,
    )


def create_pending_task(workspace_id: str, profile_id: str, scope: dict | None = None,
                        created_by: str = "user", session_id: str = "",
                        max_concurrency: int = 3, task_id: str = "") -> InspectionTask:
    """Persist a real pending task for async HTTP callers."""
    ws = _validate_workspace(workspace_id)
    coerced_scope = _coerce_scope(scope)
    if max_concurrency < 1:
        max_concurrency = 1
    if max_concurrency > 16:
        max_concurrency = 16
    return _runner_create_pending(
        workspace_id=ws,
        profile_id=profile_id,
        scope=coerced_scope,
        created_by=created_by,
        session_id=session_id,
        max_concurrency=max_concurrency,
        task_id=task_id,
    )


def start_background_task(workspace_id: str, profile_id: str, scope: dict | None = None,
                          created_by: str = "user", session_id: str = "",
                          max_concurrency: int = 3, task_id: str = "") -> InspectionTask:
    """Create a pending task and run it on a daemon worker.

    This is the default LLM/HTTP launch path for inspections. It returns quickly
    with a real task id so the UI can track/cancel and the LLM can query
    get/report later. It deliberately does not block a tool call for the
    whole fleet run.
    """
    import logging
    import threading

    pending = create_pending_task(
        workspace_id=workspace_id,
        profile_id=profile_id,
        scope=scope,
        created_by=created_by,
        session_id=session_id,
        max_concurrency=max_concurrency,
        task_id=task_id,
    )
    ensure_tracking(pending, source="background")
    if pending.status == "failed":
        return pending

    payload = {
        "workspace_id": getattr(pending, "workspace_id", "") or _validate_workspace(workspace_id),
        "profile_id": getattr(pending, "profile_id", "") or str(profile_id or ""),
        "scope": scope or {},
        "created_by": created_by,
        "session_id": session_id,
        "max_concurrency": getattr(pending, "max_concurrency", max_concurrency),
        "task_id": getattr(pending, "task_id", task_id),
    }
    logger = logging.getLogger("agent.modules.inspection.service")

    def _kick() -> None:
        try:
            create_task(**payload)
        except Exception:
            logger.exception("inspection background task crashed")
            # Directly mark the pending task as failed on disk
            try:
                from dataclasses import asdict
                from workspace.ids import validate_workspace_id
                from workspace.run_store import WS_ROOT
                from workspace.atomic_io import atomic_write_json
                ws = validate_workspace_id(workspace_id)
                tid = getattr(pending, "task_id", task_id)
                p = WS_ROOT / ws / "inspection" / "tasks" / f"{tid}.json"
                if p.is_file():
                    existing = _runner_load(ws, tid)
                    if existing is not None and existing.status == "pending":
                        existing.status = "failed"
                        existing.error = "background_worker_crashed"
                        existing.finished_at = now_iso()
                        ensure_tracking(existing, source="background_crash")
                        p.parent.mkdir(parents=True, exist_ok=True)
                        atomic_write_json(p, asdict(existing))
            except Exception:
                logger.exception("inspection: could not mark crashed task as failed")

    threading.Thread(
        target=_kick,
        name=f"inspection-{pending.task_id}",
        daemon=True,
    ).start()
    return pending


def list_tasks(workspace_id: str, *, limit: int = 50) -> list[dict]:
    """List the most recent ``limit`` inspection tasks.

    The cap (200) stops a misbehaving caller from sweeping every
    file in `inspections/` and serialising the whole history. Below
    1 we fall back to the default 50.
    """
    if limit < 1:
        limit = 50
    if limit > 200:
        limit = 200
    ws = _validate_workspace(workspace_id)
    return _runner_list(ws, limit=limit)


def get_task(workspace_id: str, task_id: str, *, record_poll: bool = True) -> Optional[InspectionTask]:
    """Load a task strictly under ``workspace_id``.

    A task id from a different workspace returns ``None`` rather
    than the wrong data, so the API can answer 404 vs 200 correctly.
    """
    if not task_id:
        return None
    ws = _validate_workspace(workspace_id)
    if record_poll:
        return _runner_record_poll(ws, task_id, source="get")
    task = _runner_load(ws, task_id)
    if task is not None:
        ensure_tracking(task, source="get_task")
    return task


def cancel_task(workspace_id: str, task_id: str) -> dict:
    ws = _validate_workspace(workspace_id)
    return _runner_cancel(ws, task_id)


def _normalise_report_fmt(fmt: str) -> str:
    """Normalise user-provided ``fmt`` to a canonical token.

    Accepts ``md`` / ``markdown`` / ``json`` / ``html``. Empty
    string and ``markdown`` map to ``md``. Unknown tokens return
    ``""`` so the caller can answer with a 400.
    """
    f = (fmt or "").lower().strip()
    if f in ("", "md", "markdown"):
        return "md"
    if f in ("json", "html"):
        return f
    return ""


def render_report(workspace_id: str, task_id: str, fmt: str = "md") -> dict:
    """Render the report in ``fmt`` (``md``, ``json``, or ``html``).

    HTML reports are persisted as artifacts; the second render of
    the same ``task_id`` reuses the existing artifact instead of
    creating a duplicate. Returns ``{"ok": True, ...}`` or
    ``{"ok": False, "error": ...}``.
    """
    fmt = _normalise_report_fmt(fmt)
    if not fmt:
        return {"ok": False, "error": f"unsupported_format: {fmt!r}"}
    task = get_task(workspace_id, task_id, record_poll=False)
    if task is None:
        return {"ok": False, "error": "task_not_found"}
    if fmt == "html":
        html = _report.render_html(task)
        existing = _find_existing_report_artifact(workspace_id, task_id, "html")
        if existing is not None:
            artifact_id = existing.get("artifact_id", "") if isinstance(existing, dict) else getattr(existing, "artifact_id", "")
            return {
                "ok": True,
                "format": "html",
                "filename": f"inspection_{task_id}.html",
                "content": html,
                "artifact_id": artifact_id,
                "download_url": f"/api/inspection/tasks/{task_id}/report.html?workspace_id={workspace_id}",
                "cached": True,
            }
        from artifacts.store import save_artifact
        art = save_artifact(
            workspace_id=workspace_id,
            content=html,
            artifact_type="report",
            title=f"inspection_{task_id}.html",
            scope="workspace",
            sensitivity="internal",
            run_id=task_id,
            capability_id="inspection",
            metadata={
                "inspection_task_id": task_id,
                "report_format": "html",
            },
            tags=["inspection", "html_report"],
            source="inspection",
        )
        if art is not None:
            artifact_id = getattr(art, "artifact_id", "")
        else:
            artifact_id = ""
        return {
            "ok": True,
            "format": "html",
            "filename": f"inspection_{task_id}.html",
            "content": html,
            "artifact_id": artifact_id,
            "download_url": f"/api/inspection/tasks/{task_id}/report.html?workspace_id={workspace_id}",
            "cached": False,
        }

    if fmt == "json":
        from dataclasses import asdict
        return {
            "ok": True,
            "format": "json",
            "filename": "inspection_report.json",
            "content": asdict(task),
        }
    md = _report.render_markdown(task)
    return {
        "ok": True,
        "format": "md",
        "filename": f"inspection_{task_id}.md",
        "content": md,
    }


def _find_existing_report_artifact(workspace_id: str, task_id: str, fmt: str):
    """Return the most recent html report artifact for ``task_id`` if any.

    We deduplicate by ``run_id == task_id`` and metadata
    ``report_format == fmt``; the *last* one is treated as canonical
    (older html files keep their artifact id but aren't reused so
    the download URL stays stable).

    Returns ``None`` if no prior render exists.
    """
    try:
        from artifacts.store import list_artifacts
    except ImportError:
        return None
    try:
        items = list_artifacts(
            workspace_id=workspace_id,
            run_id=task_id,
            artifact_type="report",
        )
    except (OSError, ValueError, TypeError):
        return None
    for it in reversed(items or ()):  # newest first
        meta = (it.get("metadata") if isinstance(it, dict) else getattr(it, "metadata", None)) or {}
        if not isinstance(meta, dict):
            continue
        if meta.get("report_format") == fmt:
            return it
    return None
