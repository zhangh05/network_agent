"""Global runtime state records."""

from __future__ import annotations

from typing import Any

import json

from storage.atomic_io import atomic_write_json
from storage.records import runtime_record_file


def save_runtime_record(name: str, value: dict[str, Any]) -> None:
    atomic_write_json(_runtime_path(name), value)


def read_runtime_record(name: str) -> dict[str, Any] | None:
    path = _runtime_path(name)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def delete_runtime_record(name: str) -> bool:
    path = _runtime_path(name)
    if not path.is_file():
        return False
    path.unlink()
    return True


def _runtime_path(name: str):
    return runtime_record_file(f"{_safe_name(name)}.json")


def _safe_name(name: str) -> str:
    text = str(name or "").strip()
    if not text or "/" in text or "\\" in text or ".." in text:
        raise ValueError("invalid runtime record name")
    return text
