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

from .models import InspectionScope, InspectionTask, InspectionProfile
from .profiles import BUILTIN_PROFILES, resolve_profile
from .runner import (
    INSPECTION_CALLER,
    cancel_task as _runner_cancel,
    list_tasks as _runner_list,
    load_task as _runner_load,
    run_task as _runner_run,
)
from . import report as _report


# ── validation ──────────────────────────────────────────────────────────

def _validate_workspace(workspace_id: str) -> str:
    ws = validate_workspace_id(workspace_id)
    return ws


def list_profiles() -> list[dict]:
    """Return all builtin profiles as plain dicts."""
    out: list[dict] = []
    for pid, prof in BUILTIN_PROFILES.items():
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
        type=str(s.get("type", "") or ""),
        vendor=str(s.get("vendor", "") or ""),
        tags=_tuple_of_strings(s.get("tags")),
        asset_ids=_tuple_of_strings(s.get("asset_ids")),
        limit=_coerce_limit(s.get("limit", 50)),
    )


def create_task(workspace_id: str, profile_id: str, scope: dict | None = None,
                created_by: str = "user", session_id: str = "",
                max_concurrency: int = 3) -> InspectionTask:
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
    return _runner_run(
        workspace_id=ws,
        profile_id=profile_id,
        scope=coerced_scope,
        created_by=created_by,
        session_id=session_id,
        max_concurrency=max_concurrency,
    )


def list_tasks(workspace_id: str, *, limit: int = 50) -> list[dict]:
    ws = _validate_workspace(workspace_id)
    return _runner_list(ws, limit=limit)


def get_task(workspace_id: str, task_id: str) -> Optional[InspectionTask]:
    """Load a task strictly under ``workspace_id``.

    A task id from a different workspace returns ``None`` rather
    than the wrong data, so the API can answer 404 vs 200 correctly.
    """
    if not task_id:
        return None
    ws = _validate_workspace(workspace_id)
    return _runner_load(ws, task_id)


def cancel_task(workspace_id: str, task_id: str) -> dict:
    ws = _validate_workspace(workspace_id)
    return _runner_cancel(ws, task_id)


def render_report(workspace_id: str, task_id: str, fmt: str = "md") -> dict:
    """Render the report in ``fmt`` (``md`` or ``json``).

    Returns ``{"ok": True, "format": ..., "content": ...}`` or
    ``{"ok": False, "error": ...}``.
    """
    task = get_task(workspace_id, task_id)
    if task is None:
        return {"ok": False, "error": "task_not_found"}
    if fmt not in ("md", "markdown"):
        if fmt == "json":
            from dataclasses import asdict
            return {
                "ok": True,
                "format": "json",
                "filename": "inspection_report.json",
                "content": asdict(task),
            }
        return {"ok": False, "error": f"unsupported_format: {fmt}"}
    md = _report.render_markdown(task)
    return {
        "ok": True,
        "format": "md",
        "filename": f"inspection_{task_id}.md",
        "content": md,
    }
