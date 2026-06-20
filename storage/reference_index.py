# storage/reference_index.py
"""Cross-reference index linking files to owner entities."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from storage.paths import workspace_root
from storage.schemas import FileReference


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ref_index_path(workspace_id: str) -> Path:
    return workspace_root(workspace_id) / "index" / "references.jsonl"


def add_reference(
    workspace_id: str,
    file_id: str,
    owner_type: str,
    owner_id: str,
    relation: str = "source",
    metadata: dict[str, Any] | None = None,
) -> FileReference:
    """Add a cross-reference between a file and an owner entity."""
    ref = FileReference(
        ref_id=f"ref_{uuid.uuid4().hex[:12]}",
        workspace_id=workspace_id,
        file_id=file_id,
        owner_type=owner_type,
        owner_id=owner_id,
        relation=relation,
        created_at=_now_iso(),
        metadata=metadata or {},
    )
    idx = _ref_index_path(workspace_id)
    idx.parent.mkdir(parents=True, exist_ok=True)
    with open(idx, "a", encoding="utf-8") as f:
        f.write(json.dumps(ref.as_dict(), ensure_ascii=False, default=str) + "\n")
    return ref


def list_references_for_file(workspace_id: str, file_id: str) -> list[dict]:
    """List all references pointing to a specific file."""
    return _query_refs(workspace_id, "file_id", file_id)


def list_references_for_owner(workspace_id: str, owner_type: str, owner_id: str) -> list[dict]:
    """List all file references owned by a specific entity."""
    return [
        r for r in _query_refs(workspace_id, "owner_id", owner_id)
        if r.get("owner_type") == owner_type
    ]


def remove_reference(workspace_id: str, ref_id: str) -> bool:
    """Remove a reference by ref_id (rewrite index)."""
    idx = _ref_index_path(workspace_id)
    if not idx.exists():
        return False
    lines = idx.read_text(encoding="utf-8").strip().split("\n")
    new_lines = []
    found = False
    for line in lines:
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
            if rec.get("ref_id") == ref_id:
                found = True
                continue
            new_lines.append(line)
        except json.JSONDecodeError:
            new_lines.append(line)
    if found:
        idx.write_text("\n".join(new_lines) + ("\n" if new_lines else ""), encoding="utf-8")
    return found


def _query_refs(workspace_id: str, key: str, value: str) -> list[dict]:
    idx = _ref_index_path(workspace_id)
    if not idx.exists():
        return []
    results = []
    for line in idx.read_text(encoding="utf-8").strip().split("\n"):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
            if rec.get(key) == value:
                results.append(rec)
        except json.JSONDecodeError:
            continue
    return results
