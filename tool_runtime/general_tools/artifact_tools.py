"""Split general tool handlers."""
from tool_runtime.general_tools.shared import *


def handle_artifact_search(inv: ToolInvocation) -> dict:
    args = inv.arguments
    ws = args.get("workspace_id", "default")
    query = (args.get("query") or "").strip().lower()
    try:
        validate_workspace_id(ws)
        from artifacts.store import list_artifacts
        arts = list_artifacts(ws, limit=100)
        results = []
        for a in arts:
            title = (a.get("title") or "").lower()
            a_type = (a.get("artifact_type") or "").lower()
            if query in title or query in a_type or not query:
                results.append({
                    "artifact_id": a.get("artifact_id", ""),
                    "title": a.get("title", ""),
                    "artifact_type": a.get("artifact_type", ""),
                    "lifecycle": a.get("lifecycle", "active"),
                    "sensitivity": a.get("sensitivity", "internal"),
                    "created_at": a.get("created_at", ""),
                })
        return _ok(inv, "", {"results": results[:20], "count": len(results)})
    except Exception as e:
        return _error_inv(inv, str(e)[:200])


def handle_artifact_read_content_safe(inv: ToolInvocation) -> dict:
    args = inv.arguments
    ws = args.get("workspace_id", "default")
    art_id = args.get("artifact_id", "")
    try:
        validate_workspace_id(ws)
        from artifacts.store import read_artifact_content, get_artifact
        art = get_artifact(ws, art_id)
        if not art:
            return _error_inv(inv, "artifact not found")
        sensitivity = getattr(art, "sensitivity", "internal")
        art_type = getattr(art, "artifact_type", "")
        if sensitivity == "secret":
            return _ok(inv, "", {
                "preview": "[artifact content not shown]",
                "title": getattr(art, "title", ""),
                "artifact_type": art_type,
                "sensitivity": sensitivity,
            })
        allow = sensitivity != "confidential"
        content = read_artifact_content(ws, art_id, allow_sensitive=allow)
        if content is None:
            return _error_inv(inv, "content not accessible")
        if art_type in ("translated_config", "output_config"):
            preview_len = min(len(str(content)), 8000)
        elif sensitivity == "confidential":
            preview_len = 200
        else:
            preview_len = 2000
        return _ok(inv, "", {
            "preview": _safe_preview(str(content), preview_len),
            "title": getattr(art, "title", ""),
            "artifact_type": art_type,
            "sensitivity": sensitivity,
        })
    except Exception as e:
        return _error_inv(inv, str(e)[:200])


def handle_artifact_save_result(inv: ToolInvocation) -> dict:
    args = inv.arguments
    ws = args.get("workspace_id", "default")
    title = args.get("title", "tool_result")
    content = str(args.get("content", ""))
    a_type = args.get("artifact_type", "knowledge_doc")
    try:
        validate_workspace_id(ws)
        from artifacts.store import save_artifact
        rec = save_artifact(workspace_id=ws, content=content, title=title,
                            artifact_type=a_type, sensitivity="internal")
        if not rec:
            return _error_inv(inv, "artifact save blocked or failed")
        return _ok(inv, "", {
            "artifact_id": rec.artifact_id,
            "artifact_ids": [rec.artifact_id],
            "title": title,
            "artifact_type": a_type,
            "file_id": getattr(rec, "file_id", ""),
        })
    except Exception as e:
        return _error_inv(inv, str(e)[:200])


def handle_artifact_tag(inv: ToolInvocation) -> dict:
    args = inv.arguments
    ws = args.get("workspace_id", "default")
    art_id = args.get("artifact_id", "")
    tags = args.get("tags", [])
    try:
        validate_workspace_id(ws)
        from artifacts.store import get_artifact, update_artifact_tags
        art = get_artifact(ws, art_id)
        if not art:
            return _error_inv(inv, "artifact not found")
        existing = list(getattr(art, "tags", []) or [])
        for t in tags:
            if t not in existing:
                existing.append(t)
        if not update_artifact_tags(ws, art_id, existing):
            return _error_inv(inv, "artifact tag update failed")
        return _ok(inv, "", {"artifact_id": art_id, "tags": existing})
    except Exception as e:
        return _error_inv(inv, str(e)[:200])


def handle_artifact_delete_soft(inv: ToolInvocation) -> dict:
    args = inv.arguments
    ws = args.get("workspace_id", "default")
    art_id = args.get("artifact_id", "")
    try:
        validate_workspace_id(ws)
        from artifacts.store import delete_artifact
        ok = delete_artifact(ws, art_id)
        return _ok(inv, f"Artifact {art_id} deleted={ok}.", {"deleted": ok}) if ok else _error_inv(inv, "delete failed")
    except Exception as e:
        return _error_inv(inv, str(e)[:200])


__all__ = ['handle_artifact_search', 'handle_artifact_read_content_safe', 'handle_artifact_save_result', 'handle_artifact_tag', 'handle_artifact_delete_soft']
