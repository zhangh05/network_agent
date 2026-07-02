# backend/api/memory_routes.py
"""Memory API routes — list and delete. v3.10: governed via MemoryWriteGate."""

from flask import request, jsonify
from backend.api.memory import _read_ws_id


def handle_memory_delete(memory_id):
    """Tombstone-delete a memory record."""
    ws_id, err = _read_ws_id(request.args.get("workspace_id", ""))
    if err:
        return jsonify({"ok": False, "error": err}), 400
    from workspace.memory_governance import reject_memory
    result = reject_memory(ws_id, memory_id)
    if not result.get("ok"):
        return jsonify({"ok": False, "error": "memory_not_found"})
    return jsonify({"ok": True, "deleted_count": 1})


def handle_memory_list():
    """List memory records."""
    ws_id, err = _read_ws_id(request.args.get("workspace_id", ""))
    if err:
        return jsonify({"ok": False, "error": err}), 400
    from workspace.memory_governance import MemoryStore
    store = MemoryStore()
    include_deleted = str(request.args.get("include_deleted", "")).lower() in {"1", "true", "yes"}
    status_filter = str(request.args.get("status", "")).strip()
    session_id = str(request.args.get("session_id", "")).strip()
    try:
        limit = int(request.args.get("limit") or 100)
    except Exception:
        limit = 100
    limit = max(1, min(limit, 500))

    records = []
    for rec in store.list_all(ws_id):
        if status_filter and rec.status != status_filter:
            continue
        if session_id and rec.session_id != session_id:
            continue
        if not include_deleted and rec.status in {"rejected", "expired"}:
            continue
        payload = rec.to_dict()
        try:
            from core.tools.redaction import redact_tool_output
            payload = redact_tool_output(payload)
        except Exception:
            pass
        records.append(payload)
        if len(records) >= limit:
            break
    return jsonify({"ok": True, "records": records, "count": len(records)})
