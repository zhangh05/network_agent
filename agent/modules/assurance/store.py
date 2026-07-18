"""Workspace-scoped atomic record store for assurance facts."""

from __future__ import annotations

import threading
from dataclasses import asdict, is_dataclass
from typing import Any

from storage.records import (
    atomic_save_json,
    clear_json_record_dir,
    delete_json_record,
    list_json_records,
    read_json_record,
)
from workspace.ids import validate_workspace_id


_LOCK = threading.RLock()
_KINDS = {
    "baselines", "checks", "snapshots", "drifts", "topologies", "incidents",
    "changes", "schedules", "operations", "alarms",
}


def record_kinds() -> tuple[str, ...]:
    """Return the assurance-owned record kinds in stable order."""
    return tuple(sorted(_KINDS))


def _parts(workspace_id: str, kind: str, record_id: str = "") -> tuple[str, ...]:
    ws = validate_workspace_id(workspace_id)
    if kind not in _KINDS:
        raise ValueError(f"unsupported assurance record kind: {kind}")
    if not record_id:
        return ("assurance", kind)
    if "/" in record_id or "\\" in record_id or ".." in record_id:
        raise ValueError("invalid assurance record id")
    return ("assurance", kind, f"{record_id}.json")


def save(workspace_id: str, kind: str, record_id: str, value: Any) -> dict[str, Any]:
    if not record_id or "/" in record_id or ".." in record_id:
        raise ValueError("invalid assurance record id")
    payload = asdict(value) if is_dataclass(value) else dict(value)
    with _LOCK:
        atomic_save_json(workspace_id, _parts(workspace_id, kind, record_id), payload)
    return payload


def get(workspace_id: str, kind: str, record_id: str) -> dict[str, Any] | None:
    if not record_id or "/" in record_id or ".." in record_id:
        return None
    try:
        data = read_json_record(workspace_id, _parts(workspace_id, kind, record_id))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def list_records(workspace_id: str, kind: str, limit: int = 100) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit or 100), 500))
    return list_json_records(workspace_id, _parts(workspace_id, kind), limit=limit)


def delete(workspace_id: str, kind: str, record_id: str) -> bool:
    with _LOCK:
        try:
            deleted = delete_json_record(workspace_id, _parts(workspace_id, kind, record_id))
        except ValueError:
            return False
    return deleted


def prune(workspace_id: str, kind: str, id_field: str, keep: int) -> int:
    """Keep the newest records of an append-only evidence kind."""
    rows = list_records(workspace_id, kind, limit=500)
    removed = 0
    for row in rows[max(1, int(keep)):]:
        record_id = str(row.get(id_field, ""))
        if record_id and delete(workspace_id, kind, record_id):
            removed += 1
    return removed


def clear_all(workspace_id: str) -> dict[str, int]:
    """Delete every assurance-owned JSON record for one workspace.

    CMDB assets, inspection tasks, raw artifacts, sessions, and reports live in
    different stores and are deliberately outside this boundary.
    """
    ws = validate_workspace_id(workspace_id)
    removed: dict[str, int] = {}
    with _LOCK:
        for kind in record_kinds():
            count = 0
            count = clear_json_record_dir(ws, _parts(ws, kind))
            removed[kind] = count
    return removed
