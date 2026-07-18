"""Workspace-scoped atomic record store for assurance facts."""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from storage.paths import workspace_root
from workspace.atomic_io import atomic_write_json
from workspace.ids import validate_workspace_id


_LOCK = threading.RLock()
_KINDS = {
    "baselines", "checks", "snapshots", "drifts", "topologies", "incidents",
    "changes", "schedules", "operations", "alarms",
}


def record_kinds() -> tuple[str, ...]:
    """Return the assurance-owned record kinds in stable order."""
    return tuple(sorted(_KINDS))


def _dir(workspace_id: str, kind: str) -> Path:
    ws = validate_workspace_id(workspace_id)
    if kind not in _KINDS:
        raise ValueError(f"unsupported assurance record kind: {kind}")
    path = workspace_root(ws) / "assurance" / kind
    path.mkdir(parents=True, exist_ok=True)
    return path


def save(workspace_id: str, kind: str, record_id: str, value: Any) -> dict[str, Any]:
    if not record_id or "/" in record_id or ".." in record_id:
        raise ValueError("invalid assurance record id")
    payload = asdict(value) if is_dataclass(value) else dict(value)
    with _LOCK:
        atomic_write_json(_dir(workspace_id, kind) / f"{record_id}.json", payload)
    return payload


def get(workspace_id: str, kind: str, record_id: str) -> dict[str, Any] | None:
    if not record_id or "/" in record_id or ".." in record_id:
        return None
    path = _dir(workspace_id, kind) / f"{record_id}.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def list_records(workspace_id: str, kind: str, limit: int = 100) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit or 100), 500))
    records: list[dict[str, Any]] = []
    for path in _dir(workspace_id, kind).glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            records.append(data)
    records.sort(
        key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""),
        reverse=True,
    )
    return records[:limit]


def delete(workspace_id: str, kind: str, record_id: str) -> bool:
    path = _dir(workspace_id, kind) / f"{record_id}.json"
    with _LOCK:
        if not path.is_file():
            return False
        path.unlink()
    return True


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
            for path in _dir(ws, kind).glob("*.json"):
                if not path.is_file():
                    continue
                path.unlink()
                count += 1
            removed[kind] = count
    return removed
