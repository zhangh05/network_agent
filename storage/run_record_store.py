"""Run-record repository helpers."""

from __future__ import annotations

import json
from typing import Any

from storage.records import workspace_record_file
from workspace.ids import validate_run_id


def read_run_sidecar(workspace_id: str, run_id: str, suffix: str = ".json") -> dict[str, Any]:
    rid = validate_run_id(run_id)
    safe_suffix = suffix if suffix in {".json", ".trace.json"} else ".json"
    path = workspace_record_file(workspace_id, "runs", f"{rid}{safe_suffix}")
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def get_run_session_id(workspace_id: str, run_id: str) -> str:
    for suffix in (".json", ".trace.json"):
        data = read_run_sidecar(workspace_id, run_id, suffix)
        session_id = str(data.get("session_id") or "")
        if session_id:
            return session_id
    return ""


def get_run(run_id: str, workspace_id: str = "default") -> dict[str, Any]:
    from workspace.run_store import get_run as _get_run

    return _get_run(run_id, workspace_id)


def list_runs(workspace_id: str = "default", limit: int = 50, **kwargs) -> list[dict[str, Any]]:
    from workspace.run_store import list_runs as _list_runs

    fetch_limit = limit
    session_id = str(kwargs.get("session_id") or "")
    if session_id:
        fetch_limit = max(limit, 100)
    rows = _list_runs(workspace_id, limit=fetch_limit)
    if session_id:
        rows = [row for row in rows if row.get("session_id") == session_id]
    return rows[:limit]


def run_sort_key(record: dict[str, Any]) -> tuple:
    from workspace.run_store import run_sort_key as _run_sort_key

    return _run_sort_key(record)
