# storage/file_store.py
"""Unified file storage layer.

All file creation in the workspace MUST go through this module.
Files are indexed in ``index/files.jsonl`` and stored under
``files/<category>/`` within the workspace.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Any, Union

from storage.paths import workspace_root, ensure_workspace_storage_dirs
from storage.schemas import FileRecord


# ── Helpers ──────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _gen_file_id() -> str:
    return f"file_{uuid.uuid4().hex[:16]}"


def _safe_name(name: str, max_len: int = 80) -> str:
    """Sanitize a filename for safe filesystem use."""
    safe = re.sub(r"[^a-zA-Z0-9_.-]", "_", name or "unnamed")
    return safe[:max_len] or "unnamed"


def _sha256_of_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _index_path(workspace_id: str) -> Path:
    return workspace_root(workspace_id) / "index" / "files.jsonl"


def _append_to_index(workspace_id: str, record: FileRecord) -> None:
    """Append a FileRecord to the workspace file index."""
    idx = _index_path(workspace_id)
    idx.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record.as_dict(), ensure_ascii=False, default=str)
    with open(idx, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _update_index_record(workspace_id: str, file_id: str, updates: dict) -> None:
    """Update a record in the JSONL index (rewrite approach for small indexes)."""
    idx = _index_path(workspace_id)
    if not idx.exists():
        return
    lines = idx.read_text(encoding="utf-8").strip().split("\n")
    new_lines = []
    for line in lines:
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
            if rec.get("file_id") == file_id:
                rec.update(updates)
            new_lines.append(json.dumps(rec, ensure_ascii=False, default=str))
        except json.JSONDecodeError:
            new_lines.append(line)
    idx.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


# ── Category path mapping ────────────────────────────────────────────

_LOGICAL_TYPE_TO_DIR = {
    "user_upload": "files/user_upload/original",
    "chat_attachment": "files/user_upload/original",
    "config_input": "files/user_upload/original",
    "pcap_input": "files/user_upload/original",
    "knowledge_source": "files/knowledge/source",
    "knowledge_normalized": "files/knowledge/normalized",
    "artifact_output": "files/agent_output/export",
    "translated_config": "files/agent_output/config",
    "pcap_result": "files/agent_output/pcap",
    "pcap_session": "files/agent_output/pcap",
    "pcap_connections": "files/agent_output/pcap",
    "report": "files/agent_output/report",
    "message_large_content": "files/agent_output/message",
    "tmp": "files/tmp",
}


def _dir_for_type(logical_type: str) -> str:
    return _LOGICAL_TYPE_TO_DIR.get(logical_type, "files/agent_output/export")


# ── Public API ───────────────────────────────────────────────────────

def create_file_record(
    workspace_id: str,
    logical_type: str,
    file_kind: str,
    path: str,
    *,
    original_name: str = "",
    mime_type: str = "",
    binary: bool = False,
    size_bytes: int = 0,
    sha256: str = "",
    created_by: str = "system",
    session_id: str = "",
    run_id: str = "",
    source: str = "",
    sensitivity: str = "internal",
    metadata: dict[str, Any] | None = None,
    file_id: str = "",
) -> FileRecord:
    """Create and index a FileRecord (file must already exist on disk)."""
    fid = file_id or _gen_file_id()
    rec = FileRecord(
        file_id=fid,
        workspace_id=workspace_id,
        logical_type=logical_type,
        file_kind=file_kind,
        path=path,
        original_name=original_name,
        mime_type=mime_type,
        binary=binary,
        size_bytes=size_bytes,
        sha256=sha256,
        created_at=_now_iso(),
        created_by=created_by,
        session_id=session_id,
        run_id=run_id,
        source=source,
        sensitivity=sensitivity,
        metadata=metadata or {},
    )
    _append_to_index(workspace_id, rec)
    return rec


def import_user_upload(
    workspace_id: str,
    file_source: Union[str, Path, IO[bytes]],
    original_name: str,
    *,
    logical_type: str = "user_upload",
    file_kind: str = "text",
    binary: bool = False,
    source: str = "user_upload",
    session_id: str = "",
    run_id: str = "",
    sensitivity: str = "internal",
    metadata: dict[str, Any] | None = None,
) -> FileRecord:
    """Import an uploaded file into managed storage, preserving the original."""
    ensure_workspace_storage_dirs(workspace_id)
    ws = workspace_root(workspace_id)
    fid = _gen_file_id()
    safe = _safe_name(original_name)
    rel_dir = _dir_for_type(logical_type)
    target_dir = ws / rel_dir
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{fid}__{safe}"
    rel_path = str(target.relative_to(ws))

    # Write file
    if isinstance(file_source, (str, Path)):
        src = Path(file_source)
        shutil.copy2(str(src), str(target))
    else:
        # File-like object (stream)
        with open(target, "wb") as out:
            while True:
                chunk = file_source.read(65536)
                if not chunk:
                    break
                out.write(chunk)

    size = target.stat().st_size
    sha = _sha256_of_file(target)
    mime = _guess_mime(original_name, binary)

    return create_file_record(
        workspace_id=workspace_id,
        logical_type=logical_type,
        file_kind=file_kind,
        path=rel_path,
        original_name=original_name,
        mime_type=mime,
        binary=binary,
        size_bytes=size,
        sha256=sha,
        source=source,
        session_id=session_id,
        run_id=run_id,
        sensitivity=sensitivity,
        metadata=metadata,
        file_id=fid,
    )


def write_agent_output(
    workspace_id: str,
    content: Union[str, bytes],
    logical_type: str,
    file_kind: str,
    *,
    title: str = "",
    ext: str = "",
    source: str = "agent",
    run_id: str = "",
    session_id: str = "",
    sensitivity: str = "internal",
    metadata: dict[str, Any] | None = None,
) -> FileRecord:
    """Write agent-generated output to managed storage."""
    ensure_workspace_storage_dirs(workspace_id)
    ws = workspace_root(workspace_id)
    fid = _gen_file_id()
    safe_title = _safe_name(title or fid)
    if not ext:
        ext = _ext_for_kind(file_kind)
    rel_dir = _dir_for_type(logical_type)
    target_dir = ws / rel_dir
    target_dir.mkdir(parents=True, exist_ok=True)

    # Write to tmp first, then rename (atomic-ish)
    tmp_dir = ws / "files" / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_file = tmp_dir / f"{fid}.tmp"
    target = target_dir / f"{fid}__{safe_title}.{ext}"
    rel_path = str(target.relative_to(ws))

    is_binary = isinstance(content, bytes)
    if is_binary:
        tmp_file.write_bytes(content)
    else:
        tmp_file.write_text(content, encoding="utf-8")

    shutil.move(str(tmp_file), str(target))

    size = target.stat().st_size
    data = content if is_binary else content.encode("utf-8")
    sha = _sha256_of_bytes(data)

    return create_file_record(
        workspace_id=workspace_id,
        logical_type=logical_type,
        file_kind=file_kind,
        path=rel_path,
        original_name=f"{safe_title}.{ext}",
        mime_type=_guess_mime(f"{safe_title}.{ext}", is_binary),
        binary=is_binary,
        size_bytes=size,
        sha256=sha,
        source=source,
        run_id=run_id,
        session_id=session_id,
        sensitivity=sensitivity,
        metadata=metadata,
        file_id=fid,
    )


def read_file_content(workspace_id: str, file_id: str) -> str:
    """Read text content of a managed file by file_id."""
    rec = get_file_record(workspace_id, file_id)
    if not rec:
        raise FileNotFoundError(f"No file record for {file_id}")
    path = resolve_file_path(workspace_id, file_id)
    return path.read_text(encoding="utf-8", errors="replace")


def resolve_file_path(workspace_id: str, file_id: str) -> Path:
    """Resolve a file_id to its absolute filesystem path."""
    rec = get_file_record(workspace_id, file_id)
    if not rec:
        raise FileNotFoundError(f"No file record for {file_id}")
    ws = workspace_root(workspace_id)
    resolved = (ws / rec["path"]).resolve()
    # Path traversal check
    if not str(resolved).startswith(str(ws.resolve())):
        raise ValueError(f"Path escape denied for {file_id}")
    if not resolved.exists():
        raise FileNotFoundError(f"File not found on disk: {rec['path']}")
    return resolved


def get_file_record(workspace_id: str, file_id: str) -> dict | None:
    """Look up a FileRecord from the JSONL index."""
    idx = _index_path(workspace_id)
    if not idx.exists():
        return None
    for line in idx.read_text(encoding="utf-8").strip().split("\n"):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
            if rec.get("file_id") == file_id:
                return rec
        except json.JSONDecodeError:
            continue
    return None


def list_files(workspace_id: str, *, logical_type: str = "", lifecycle: str = "active") -> list[dict]:
    """List file records, optionally filtered by logical_type and lifecycle."""
    idx = _index_path(workspace_id)
    if not idx.exists():
        return []
    results = []
    for line in idx.read_text(encoding="utf-8").strip().split("\n"):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if lifecycle and rec.get("lifecycle") != lifecycle:
            continue
        if logical_type and rec.get("logical_type") != logical_type:
            continue
        results.append(rec)
    return results


def soft_delete_file(workspace_id: str, file_id: str) -> bool:
    """Mark a file as soft-deleted (does not remove from disk)."""
    rec = get_file_record(workspace_id, file_id)
    if not rec:
        return False
    _update_index_record(workspace_id, file_id, {
        "lifecycle": "soft_deleted",
        "metadata": {**rec.get("metadata", {}), "deleted_at": _now_iso()},
    })
    return True


# ── Internal helpers ─────────────────────────────────────────────────

def _guess_mime(name: str, binary: bool = False) -> str:
    ext = Path(name).suffix.lower()
    mime_map = {
        ".txt": "text/plain", ".md": "text/markdown", ".json": "application/json",
        ".yaml": "text/yaml", ".yml": "text/yaml", ".xml": "text/xml",
        ".csv": "text/csv", ".html": "text/html", ".log": "text/plain",
        ".pdf": "application/pdf", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".pcap": "application/vnd.tcpdump.pcap", ".pcapng": "application/vnd.tcpdump.pcap",
    }
    return mime_map.get(ext, "application/octet-stream" if binary else "text/plain")


def _ext_for_kind(kind: str) -> str:
    ext_map = {
        "text": "txt", "config": "txt", "markdown": "md", "json": "json",
        "yaml": "yaml", "xml": "xml", "csv": "csv", "html": "html",
        "log": "log", "diff": "diff", "script": "sh",
    }
    return ext_map.get(kind, "txt")
