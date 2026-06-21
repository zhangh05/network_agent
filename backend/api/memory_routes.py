# backend/api/memory_routes.py
"""Memory API routes — list, delete, confirm."""

from flask import request, jsonify
from backend.api.params import parse_limit
from memory.store import get_store
from memory.redaction import contains_secret


def handle_memory_confirm():
    """User-confirmed memory write — used by AgentWorkbench to save conclusions as decisions."""
    data = request.get_json(silent=True) or {}
    memory_type = data.get("memory_type", "decision")
    title = data.get("title", "")
    content = data.get("content", "")
    tags = data.get("tags", [])
    workspace_id = data.get("workspace_id", "")

    if not content and not title:
        return jsonify({"ok": False, "error": "title or content required"}), 400

    if contains_secret(content):
        return jsonify({"ok": False, "error": "Content contains secrets; redaction required"}), 400

    from memory.writer import write_memory
    mid = write_memory(
        title=title, content=content,
        scope="long_term", memory_type=memory_type,
        tags=tags, workspace_id=workspace_id,
        source="user", confidence="user_confirmed",
        sensitivity="internal", user_confirmed=True,
    )

    if not mid:
        return jsonify({"ok": False, "error": "Blocked by policy"}), 400

    record = get_store().get(mid)
    meta = (record.get("metadata") or {}) if record else {}
    return jsonify({
        "ok": True,
        "memory_id": mid,
        "redaction_applied": False,
        "conflict_detected": bool(meta.get("conflict_detected")),
        "conflicts": list(meta.get("conflicts") or []),
    })


def _get_deleted_records(store) -> list:
    """Get tombstoned (soft-deleted) records from the store."""
    try:
        deleted = store.list_deleted() if hasattr(store, 'list_deleted') else []
        for d in deleted:
            if isinstance(d, dict):
                d["_tombstone"] = True
            elif hasattr(d, 'as_dict'):
                dd = d.as_dict()
                dd["_tombstone"] = True
                deleted[deleted.index(d)] = dd
        return deleted
    except Exception:
        return []


def handle_memory_delete(memory_id):
    """Tombstone-delete a memory record."""
    store = get_store()
    record = store.get(str(memory_id))
    if not record:
        return jsonify({"ok": False, "error": "memory_not_found"})
    ok = store.delete(str(memory_id))
    projection = {"ok": True, "deleted_count": 0}
    if ok:
        try:
            from memory.indexer import delete_memory_projection
            # Use workspace_id from query param first, fallback to stored workspace_id
            ws_id = request.args.get("workspace_id") or record.get("workspace_id", "") if record else ""
            projection = delete_memory_projection(str(memory_id), workspace_id=ws_id or "")
        except Exception as exc:
            projection = {"ok": False, "error": str(exc)[:160], "deleted_count": 0}
    return jsonify({"ok": ok, "rag_projection": projection})


def handle_memory_list():
    """List memory records with optional filters.

    v3.1.1: Adds frontend-aligned fields: status, value_preview.
    Supports include_deleted to show tombstoned records.
    """
    scope = request.args.get("scope")
    memory_type = request.args.get("memory_type")
    # workspace_id is the canonical field name (was project_id)
    workspace_id = request.args.get("workspace_id") or None
    include_deleted = request.args.get("include_deleted", "false").lower() == "true"
    try:
        limit = parse_limit(request.args, default=100, max_value=500)
    except ValueError:
        return jsonify({"ok": False, "error": "invalid_limit"}), 400

    store = get_store()
    records = store.list(
        scope=scope, memory_type=memory_type,
        workspace_id=workspace_id, limit=limit,
    )

    # Include tombstoned records if requested
    if include_deleted:
        deleted = _get_deleted_records(store)
        records = records + deleted

    # Normalize and enrich for frontend
    clean = []
    for r in records:
        if isinstance(r, dict):
            d = dict(r)
        elif hasattr(r, 'as_dict'):
            d = r.as_dict()
        else:
            d = {"title": str(r), "content": str(r)}

        # Derive status: deleted vs confirmed (v3.2.1: removed pending_confirmation)
        is_deleted = d.pop("_deleted", False) if isinstance(d, dict) else False
        if is_deleted or d.get("_tombstone"):
            d["status"] = "deleted"
        else:
            d["status"] = "confirmed"

        # v3.1.1: Add value_preview for list display
        d["value_preview"] = d.get("summary", "") or (d.get("content", "") or "")[:100]
        clean.append(d)

    return jsonify({
        "ok": True,
        "records": clean,
        "count": len(clean),
    })
