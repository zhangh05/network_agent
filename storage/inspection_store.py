"""Filesystem-backed inspection repositories."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from storage.records import (
    atomic_save_json,
    delete_json_record,
    list_json_records,
    read_json_record,
)
from storage.atomic_io import atomic_write_json, safe_read_json
from storage import paths as storage_paths
from workspace.ids import validate_workspace_id
from storage.workspace_store import list_workspace_ids as _list_workspace_ids

_SCRIPT_TYPES = {"general", "log"}


def save_task(workspace_id: str, task_id: str, value: dict[str, Any]) -> None:
    atomic_save_json(workspace_id, ("inspection", "tasks", f"{task_id}.json"), value)


def load_task(workspace_id: str, task_id: str) -> dict[str, Any] | None:
    return read_json_record(workspace_id, ("inspection", "tasks", f"{task_id}.json"))


def list_tasks(workspace_id: str, limit: int = 50) -> list[dict[str, Any]]:
    return list_json_records(
        workspace_id,
        ("inspection", "tasks"),
        limit=limit,
        sort_key=lambda item: str(item.get("task_id") or item.get("created_at") or ""),
    )


def reconcile_running_tasks(workspace_id: str, finished_at: str, root_override: Path | None = None) -> int:
    root = _task_dir_for_scan(workspace_id, root_override)
    if not root.exists():
        return 0
    flipped = 0
    for path in root.glob("ins_*.json"):
        try:
            data = safe_read_json(path, default=None)
        except Exception:
            continue
        if not data or data.get("status") != "running":
            continue
        data["status"] = "crashed"
        data["error"] = data.get("error", "") or "backend_restart_during_run"
        data["finished_at"] = finished_at
        try:
            if root_override is not None:
                atomic_write_json(path, data)
            else:
                atomic_save_json(workspace_id, ("inspection", "tasks", path.name), data)
            flipped += 1
        except Exception:
            continue
    return flipped


def list_workspace_ids(root: Path | None = None) -> list[str]:
    return _list_workspace_ids(root)


def load_vendor_script(workspace_id: str, vendor: str, script_type: str = "general") -> dict[str, Any] | None:
    return read_json_record(workspace_id, _script_parts(vendor, script_type))


def save_vendor_script(
    workspace_id: str,
    vendor: str,
    script_type: str,
    value: dict[str, Any],
) -> None:
    atomic_save_json(workspace_id, _script_parts(vendor, script_type), value)


def delete_vendor_script(workspace_id: str, vendor: str, script_type: str = "general") -> bool:
    return delete_json_record(workspace_id, _script_parts(vendor, script_type))


def _script_parts(vendor: str, script_type: str) -> tuple[str, ...]:
    stype = script_type if script_type in _SCRIPT_TYPES else "general"
    safe_vendor = str(vendor or "").strip()
    if not safe_vendor or "/" in safe_vendor or "\\" in safe_vendor or ".." in safe_vendor:
        raise ValueError("invalid inspection vendor script id")
    return ("inspection", "scripts", stype, f"{safe_vendor}.json")


def _task_dir_for_scan(workspace_id: str, root_override: Path | None = None) -> Path:
    ws = validate_workspace_id(workspace_id)
    if root_override is not None:
        return root_override / ws / "inspection" / "tasks"
    return _workspace_root() / ws / "inspection" / "tasks"


def _workspace_root() -> Path:
    return storage_paths.get_workspace_root()
