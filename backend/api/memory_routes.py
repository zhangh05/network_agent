# backend/api/memory_routes.py
"""Memory API routes — list and delete. v3.10: governed via MemoryWriteGate."""

from flask import request, jsonify


def _read_ws_id(raw: str):
    if not raw:
        return "", "workspace_id required"
    try:
        from workspace.ids import validate_workspace_id
        return validate_workspace_id(raw), ""
    except Exception:
        return "", "invalid_workspace_id"


def handle_memory_delete(memory_id):
    """Tombstone-delete a memory record."""
    ws_id, err = _read_ws_id(request.args.get("workspace_id", ""))
    if err:
        return jsonify({"ok": False, "error": err}), 400
    from workspace.memory_governance import MemoryStore, MemoryWriteGate
    store = MemoryStore()
    rec = store.get(ws_id, memory_id)
    if not rec:
        return jsonify({"ok": False, "error": "memory_not_found"})
    rec.status = "rejected"
    gate = MemoryWriteGate()
    result = gate.write(rec)
    if not result.get("ok", False):
        return jsonify(result)
    return jsonify({"ok": True, "deleted_count": 1})


def handle_memory_list():
    """List memory records."""
    ws_id, err = _read_ws_id(request.args.get("workspace_id", ""))
    if err:
        return jsonify({"ok": False, "error": err}), 400
    from workspace.memory_governance import MemoryStore
    store = MemoryStore()
    records = store.list_retrievable(ws_id)
    return jsonify({"ok": True, "records": records, "count": len(records)})
