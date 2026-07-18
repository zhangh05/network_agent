"""Workspace-scoped record persistence helpers.

Business modules should not need to know where JSON/JSONL records live under a
workspace. This module is the filesystem-backed adapter for small structured
records; callers pass logical store names and receive plain dicts.
"""

from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from storage import paths as storage_paths
from workspace.atomic_io import atomic_write_json
from workspace.ids import validate_workspace_id

_LOCKS: dict[str, threading.RLock] = {}
_GLOBAL_LOCK = threading.RLock()


def _lock_for(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _GLOBAL_LOCK:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _LOCKS[key] = lock
        return lock


def workspace_record_dir(workspace_id: str, *parts: str) -> Path:
    ws = validate_workspace_id(workspace_id)
    if not parts:
        raise ValueError("record directory requires at least one path part")
    safe_parts = [_safe_part(part, allow_ext=False) for part in parts]
    path = storage_paths.workspace_root(ws).joinpath(*safe_parts)
    path.mkdir(parents=True, exist_ok=True)
    return path


def workspace_record_file(workspace_id: str, *parts: str) -> Path:
    if not parts:
        raise ValueError("record file requires at least one path part")
    parent = workspace_record_dir(workspace_id, *parts[:-1])
    return parent / _safe_part(parts[-1], allow_ext=True)


@contextmanager
def jsonl_transaction(workspace_id: str, parts: Iterable[str]):
    """Hold the adapter lock for a JSONL record file."""
    path = workspace_record_file(workspace_id, *tuple(parts))
    lock = _lock_for(path)
    with lock:
        yield


def append_jsonl(workspace_id: str, parts: Iterable[str], record: dict[str, Any]) -> dict[str, Any]:
    path = workspace_record_file(workspace_id, *tuple(parts))
    payload = dict(record)
    with _lock_for(path):
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    return payload


def read_jsonl(workspace_id: str, parts: Iterable[str]) -> list[dict[str, Any]]:
    path = workspace_record_file(workspace_id, *tuple(parts))
    if not path.exists():
        return []
    with _lock_for(path):
        raw = path.read_text(encoding="utf-8")
    rows: list[dict[str, Any]] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            rows.append(data)
    return rows


def rewrite_jsonl(
    workspace_id: str,
    parts: Iterable[str],
    rows: Iterable[dict[str, Any] | str],
) -> None:
    path = workspace_record_file(workspace_id, *tuple(parts))
    lines: list[str] = []
    for row in rows:
        if isinstance(row, str):
            if row.strip():
                lines.append(row)
        else:
            lines.append(json.dumps(dict(row), ensure_ascii=False, default=str))
    with _lock_for(path):
        path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def atomic_save_json(workspace_id: str, parts: Iterable[str], value: Any) -> dict[str, Any]:
    path = workspace_record_file(workspace_id, *tuple(parts))
    payload = asdict(value) if is_dataclass(value) else dict(value)
    with _lock_for(path):
        atomic_write_json(path, payload)
    return payload


def read_json_record(workspace_id: str, parts: Iterable[str]) -> dict[str, Any] | None:
    path = workspace_record_file(workspace_id, *tuple(parts))
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def list_json_records(
    workspace_id: str,
    parts: Iterable[str],
    *,
    limit: int = 100,
    sort_key: Callable[[dict[str, Any]], str] | None = None,
) -> list[dict[str, Any]]:
    directory = workspace_record_dir(workspace_id, *tuple(parts))
    records: list[dict[str, Any]] = []
    for path in directory.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            records.append(data)
    key = sort_key or (lambda item: str(item.get("updated_at") or item.get("created_at") or ""))
    records.sort(key=key, reverse=True)
    return records[: max(1, min(int(limit or 100), 500))]


def delete_json_record(workspace_id: str, parts: Iterable[str]) -> bool:
    path = workspace_record_file(workspace_id, *tuple(parts))
    with _lock_for(path):
        if not path.is_file():
            return False
        path.unlink()
    return True


def clear_json_record_dir(workspace_id: str, parts: Iterable[str]) -> int:
    directory = workspace_record_dir(workspace_id, *tuple(parts))
    count = 0
    with _lock_for(directory):
        for path in directory.glob("*.json"):
            if not path.is_file():
                continue
            path.unlink()
            count += 1
    return count


def _safe_part(part: str, *, allow_ext: bool) -> str:
    text = str(part or "").strip()
    if not text or text in {".", ".."} or "/" in text or "\\" in text:
        raise ValueError("invalid record path part")
    if not allow_ext and "." in text:
        raise ValueError("invalid record directory part")
    return text
