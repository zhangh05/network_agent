"""Workspace discovery repository."""

from __future__ import annotations

from pathlib import Path

from storage.paths import get_workspace_root
from workspace.ids import validate_workspace_id


def list_workspace_ids(root: Path | None = None) -> list[str]:
    base = root or get_workspace_root()
    if not base.is_dir():
        return []
    ids: list[str] = []
    for path in base.iterdir():
        if not path.is_dir() or path.name.startswith("_"):
            continue
        try:
            ids.append(validate_workspace_id(path.name))
        except (TypeError, ValueError):
            continue
    return ids
