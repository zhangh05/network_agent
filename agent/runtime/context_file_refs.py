"""Explicit file-reference extraction for prompt context.

Only explicit user references are resolved. This module never scans arbitrary
filesystem paths and never follows absolute paths; managed file_id is preferred.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

MAX_FILE_REF_CHARS = 4000

_FILE_ID_RE = re.compile(r"(?:file_id\s*=\s*|@file:|file:)(file_[A-Za-z0-9_-]+)")
_REL_FILE_RE = re.compile(r"@file:([A-Za-z0-9_./-]+\.[A-Za-z0-9_-]{1,12})")


def extract_explicit_file_refs(user_input: str) -> list[dict[str, str]]:
    """Extract explicit file references from user text.

    Supported forms:
    - file_id=file_xxx
    - @file:file_xxx
    - file:file_xxx
    - @file:relative/path.txt
    """
    text = str(user_input or "")
    refs: list[dict[str, str]] = []
    seen = set()
    for match in _FILE_ID_RE.finditer(text):
        fid = match.group(1)
        key = ("file_id", fid)
        if key not in seen:
            refs.append({"kind": "file_id", "value": fid})
            seen.add(key)
    for match in _REL_FILE_RE.finditer(text):
        path = match.group(1)
        if path.startswith("file_"):
            continue
        key = ("path", path)
        if key not in seen:
            refs.append({"kind": "path", "value": path})
            seen.add(key)
    return refs[:5]


def resolve_explicit_file_refs(
    workspace_id: str,
    user_input: str,
    *,
    max_chars: int = MAX_FILE_REF_CHARS,
) -> list[dict[str, Any]]:
    """Resolve explicit file references into safe, bounded prompt evidence."""
    results = []
    for ref in extract_explicit_file_refs(user_input):
        if ref["kind"] == "file_id":
            results.append(_resolve_file_id(workspace_id, ref["value"], max_chars=max_chars))
        elif ref["kind"] == "path":
            results.append(_resolve_workspace_path(workspace_id, ref["value"], max_chars=max_chars))
    return results


def _resolve_file_id(workspace_id: str, file_id: str, *, max_chars: int) -> dict[str, Any]:
    base = {
        "ref_type": "file_id",
        "file_id": file_id,
        "verified": False,
        "status": "unverified",
    }
    try:
        from storage.file_store import get_file_record, read_file_content
        rec = get_file_record(workspace_id, file_id)
        if not rec:
            return {**base, "reason": "file_id_not_found"}
        if rec.get("binary"):
            return {
                **base,
                "verified": True,
                "status": "binary_skipped",
                "title": rec.get("original_name") or file_id,
                "size_bytes": rec.get("size_bytes", 0),
                "reason": "binary_file_not_inlined",
            }
        text = read_file_content(workspace_id, file_id)
        return {
            **base,
            "verified": True,
            "status": "verified",
            "title": rec.get("original_name") or file_id,
            "size_bytes": rec.get("size_bytes", 0),
            "content": _safe_preview(text, max_chars),
            "truncated": len(text) > max_chars,
        }
    except Exception as exc:
        return {**base, "reason": str(exc)[:160]}


def _resolve_workspace_path(workspace_id: str, rel_path: str, *, max_chars: int) -> dict[str, Any]:
    base = {
        "ref_type": "path",
        "path": rel_path,
        "verified": False,
        "status": "unverified",
    }
    try:
        from storage.paths import workspace_root
        p = Path(rel_path)
        if p.is_absolute():
            return {**base, "reason": "absolute_path_not_allowed"}
        root = workspace_root(workspace_id).resolve()
        target = (root / p).resolve()
        target.relative_to(root)
        if not target.is_file():
            return {**base, "reason": "path_not_found"}
        text = target.read_text(encoding="utf-8", errors="replace")
        return {
            **base,
            "verified": True,
            "status": "verified",
            "title": target.name,
            "size_bytes": target.stat().st_size,
            "content": _safe_preview(text, max_chars),
            "truncated": len(text) > max_chars,
        }
    except Exception as exc:
        return {**base, "reason": str(exc)[:160]}


def _safe_preview(text: str, max_chars: int) -> str:
    from workspace.redaction import redact_text
    return redact_text(str(text or ""))[:max(0, max_chars)]
