"""Workspace status aggregation."""

from __future__ import annotations

from storage.paths import workspace_root


def workspace_exists(workspace_id: str) -> bool:
    return workspace_root(workspace_id).is_dir()


def index_health(workspace_id: str) -> str:
    ws = workspace_root(workspace_id)
    for idx_name in ("files.jsonl", "references.jsonl", "artifacts.jsonl"):
        idx = ws / "index" / idx_name
        if idx.exists() and idx.is_file():
            return "ok"
    return "missing"
