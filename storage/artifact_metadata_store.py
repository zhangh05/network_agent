"""Storage-owned artifact metadata projection helpers."""

from __future__ import annotations

import json
import uuid
from typing import Any

from storage.atomic_io import atomic_write_json, atomic_write_text
from storage.ids import validate_workspace_id
from storage.paths import workspace_root
from storage.time_utils import now_iso


def create_artifact_metadata(
    *,
    workspace_id: str,
    file_record: Any,
    artifact_type: str,
    title: str,
    scope: str = "workspace",
    sensitivity: str = "internal",
    run_id: str = "",
    session_id: str = "",
    source: str = "storage",
    metadata: dict | None = None,
    created_by: str = "",
) -> dict:
    ws_id = validate_workspace_id(workspace_id)
    artifact_id = f"art_{uuid.uuid4().hex[:16]}"
    now = now_iso()
    record = {
        "artifact_id": artifact_id,
        "workspace_id": ws_id,
        "session_id": session_id,
        "run_id": run_id,
        "module": "",
        "skill": "",
        "capability_id": "",
        "artifact_type": artifact_type or "unknown",
        "title": title or artifact_type or artifact_id,
        "summary": "",
        "description": "",
        "scope": scope,
        "sensitivity": sensitivity,
        "lifecycle": "active",
        "path": str(getattr(file_record, "path", "") or ""),
        "relative_path": str(getattr(file_record, "path", "") or ""),
        "mime_type": "text/plain",
        "file_ext": str(getattr(file_record, "file_kind", "") or "txt"),
        "size_bytes": int(getattr(file_record, "size_bytes", 0) or 0),
        "sha256": str(getattr(file_record, "sha256", "") or ""),
        "file_id": str(getattr(file_record, "file_id", "") or ""),
        "source": source,
        "created_by": str(created_by or "")[:160],
        "created_at": now,
        "updated_at": now,
        "expires_at": None,
        "metadata": dict(metadata or {}),
        "tags": [],
        "redaction_applied": True,
        "parent_artifact_id": None,
        "derived_from": [],
        "references": [],
    }
    _upsert_record(ws_id, record)
    _append_index(ws_id, artifact_id)
    return record


def _upsert_record(workspace_id: str, record: dict) -> None:
    path = workspace_root(workspace_id) / "index" / "artifacts.jsonl"
    records: list[dict] = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict) and data.get("artifact_id") != record["artifact_id"]:
                records.append(data)
    records.append(record)
    atomic_write_text(
        path,
        "\n".join(json.dumps(item, ensure_ascii=False, default=str) for item in records) + "\n",
    )


def _append_index(workspace_id: str, artifact_id: str) -> None:
    path = workspace_root(workspace_id) / "sys" / "artifacts.index.json"
    data = {"workspace_id": workspace_id, "artifact_ids": [], "artifact_count": 0, "updated_at": ""}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data.update(loaded)
        except json.JSONDecodeError:
            pass
    ids = list(data.get("artifact_ids") or [])
    if artifact_id not in ids:
        ids.append(artifact_id)
    data.update({
        "workspace_id": workspace_id,
        "artifact_ids": ids,
        "artifact_count": len(ids),
        "updated_at": now_iso(),
    })
    atomic_write_json(path, data)
