# tool_runtime/general_tools/filestore_tools.py
"""FileStore tools - file.get, file.preview, file.references, file.write_agent_output, file.import_workspace_path."""

from __future__ import annotations

from typing import Any, Optional


def handle_file_get(inv, *, file_id: str = "", limit: int = 2000) -> dict[str, Any]:
    """Read text content of a managed file by file_id."""
    from storage.file_store import get_file_record, read_file_content

    rec = get_file_record(inv.workspace_id or "default", file_id)
    if not rec:
        return {"ok": False, "error": "file_not_found", "file_id": file_id}
    if rec.get("binary"):
        return {
            "ok": True, "file_id": file_id,
            "file_kind": rec.get("file_kind"), "size_bytes": rec.get("size_bytes"),
            "sha256": rec.get("sha256"), "path": rec.get("path"),
        }
    try:
        content = read_file_content(inv.workspace_id or "default", file_id)
        return {"ok": True, "file_id": file_id, "content": content[:limit],
                "size_bytes": rec.get("size_bytes"), "truncated": len(content) > limit}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:200], "file_id": file_id}


def handle_file_preview(inv, *, file_id: str = "", limit: int = 500) -> dict[str, Any]:
    """Preview a managed file's metadata and text preview."""
    from storage.file_store import get_file_record, read_file_content

    rec = get_file_record(inv.workspace_id or "default", file_id)
    if not rec:
        return {"ok": False, "error": "file_not_found", "file_id": file_id}
    result: dict[str, Any] = {
        "ok": True, "file_id": file_id,
        "file_kind": rec.get("file_kind"), "binary": rec.get("binary"),
        "size_bytes": rec.get("size_bytes"), "sha256": rec.get("sha256"),
        "path": rec.get("path"), "logical_type": rec.get("logical_type"),
    }
    if not rec.get("binary"):
        try:
            content = read_file_content(inv.workspace_id or "default", file_id)
            result["preview"] = content[:limit]
            result["truncated"] = len(content) > limit
        except Exception:
            pass
    return result


def handle_file_references(inv, *, file_id: str = "") -> dict[str, Any]:
    """Query ReferenceIndex for a file."""
    from storage.reference_index import list_references_for_file

    refs = list_references_for_file(inv.workspace_id or "default", file_id)
    return {"ok": True, "file_id": file_id, "references": refs, "count": len(refs)}


def handle_file_write_agent_output(
    inv, *, content: str = "", logical_type: str = "artifact_output",
    file_kind: str = "text", title: str = "", ext: str = "txt",
) -> dict[str, Any]:
    """Write content through FileStore.write_agent_output."""
    from storage.file_store import write_agent_output

    rec = write_agent_output(
        workspace_id=inv.workspace_id or "default",
        content=content, logical_type=logical_type, file_kind=file_kind,
        title=title or "agent_output", ext=ext,
        source="tool_runtime", run_id=getattr(inv, "run_id", ""),
    )
    return {"ok": True, "file_id": rec.file_id, "path": rec.path,
            "size_bytes": rec.size_bytes, "sha256": rec.sha256}


def handle_file_import_workspace_path(inv, *, filepath: str = "") -> dict[str, Any]:
    """Import a workspace-managed file into FileStore."""
    from pathlib import Path
    from storage.file_store import import_user_upload
    from storage.paths import workspace_root

    ws = workspace_root(inv.workspace_id or "default")
    target = (ws / filepath).resolve()
    try:
        target.relative_to(ws)
    except ValueError:
        return {"ok": False, "error": "path_not_in_workspace", "filepath": filepath}

    allowed = {"files/user_upload", "files/agent_output", "files/knowledge", "inbox"}
    if not any(str(target.relative_to(ws)).startswith(a) for a in allowed):
        return {"ok": False, "error": "filepath not in allowed current dirs", "filepath": filepath}

    if not target.exists():
        return {"ok": False, "error": "file_not_found", "filepath": filepath}

    rec = import_user_upload(
        workspace_id=inv.workspace_id or "default",
        file_source=str(target), original_name=target.name,
        source="file_import_workspace_path",
    )
    return {"ok": True, "file_id": rec.file_id, "path": rec.path,
            "size_bytes": rec.size_bytes, "sha256": rec.sha256}
