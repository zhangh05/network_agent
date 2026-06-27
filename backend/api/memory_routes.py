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
    records = store.list_retrievable(ws_id)
    return jsonify({"ok": True, "records": records, "count": len(records)})
