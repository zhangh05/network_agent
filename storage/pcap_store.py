"""Filesystem-backed PCAP session repository."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from storage.file_store import resolve_file_path
from storage.records import append_jsonl, mutate_jsonl, read_jsonl
from storage.reference_index import add_reference

_SESSION_INDEX = ("index", "pcap_sessions.jsonl")


def resolve_managed_file(workspace_id: str, file_id: str) -> Path:
    return resolve_file_path(workspace_id, file_id)


def save_session(workspace_id: str, record: dict[str, Any]) -> None:
    append_jsonl(workspace_id, _SESSION_INDEX, record)


def add_source_reference(workspace_id: str, file_id: str, session_id: str) -> None:
    add_reference(workspace_id, file_id, "pcap_session", session_id, "source")


def delete_session(workspace_id: str, session_id: str) -> None:
    mutate_jsonl(
        workspace_id,
        _SESSION_INDEX,
        lambda rows: ([row for row in rows if row.get("session_id") != session_id], None),
    )


def list_sessions(workspace_id: str, limit: int = 20) -> list[dict[str, Any]]:
    sessions: list[dict[str, Any]] = []
    seen = set()
    deleted = set()
    for rec in reversed(read_jsonl(workspace_id, _SESSION_INDEX)):
        sid = rec.get("session_id", "")
        if not sid:
            continue
        if rec.get("deleted"):
            deleted.add(sid)
            continue
        if sid not in seen and sid not in deleted:
            seen.add(sid)
            sessions.append(rec)
        if len(sessions) >= limit:
            break
    return sessions


def get_session(workspace_id: str, session_id: str) -> dict[str, Any] | None:
    for rec in reversed(read_jsonl(workspace_id, _SESSION_INDEX)):
        if rec.get("session_id") == session_id:
            return None if rec.get("deleted") else rec
    return None
