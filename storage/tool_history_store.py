"""Persistent tool execution history store."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from storage.atomic_io import atomic_write_json, safe_read_json
from workspace.ids import validate_workspace_id

_DATA_ROOT = Path(__file__).resolve().parent.parent / "data"


def save_history(workspace_id: str, entries: list[dict[str, Any]]) -> None:
    atomic_write_json(_history_path(workspace_id), entries, indent=2)


def load_history(workspace_id: str) -> list[dict[str, Any]]:
    items = safe_read_json(_history_path(workspace_id), default=[]) or []
    return items if isinstance(items, list) else []


def _history_path(workspace_id: str) -> Path:
    safe_ws = validate_workspace_id(workspace_id)
    _DATA_ROOT.mkdir(parents=True, exist_ok=True)
    return _DATA_ROOT / f"tool_history_{safe_ws}.json"
