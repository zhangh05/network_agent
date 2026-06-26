# backend/api/memory_routes.py
"""Memory API routes — list, delete, confirm. v3.10: governed via MemoryWriteGate."""

from flask import request, jsonify


def handle_memory_confirm():
    """User-confirmed memory write."""
    data = request.get_json(silent=True) or {}
    title = data.get("title", "")
    content = data.get("content", "")
    workspace_id = data.get("workspace_id", "")
    if not workspace_id:
        return jsonify({"ok": False, "error": "workspace_id required"}), 400

    from workspace.memory_governance import MemoryRecord, MemoryWriteGate
    gate = MemoryWriteGate()
    rec = MemoryRecord(
        workspace_id=workspace_id,
        scope=data.get("scope", "workspace"),
        memory_type=data.get("memory_type", "decision"),
        status="active", source="user",
        content=content[:2000], summary=title[:200],
        confidence=1.0,
        citations=data.get("citations", []),
        created_by="user",
        redacted=True,
    )
    result = gate.write(rec)
    return jsonify(result)


def handle_memory_delete(memory_id):
    """Tombstone-delete a memory record."""
    ws_id = request.args.get("workspace_id", "")
    if not ws_id:
        return jsonify({"ok": False, "error": "workspace_id required"}), 400
    from workspace.memory_governance import MemoryStore
    store = MemoryStore()
    rec = store.get(ws_id, memory_id)
    if not rec:
        return jsonify({"ok": False, "error": "memory_not_found"})
    rec.status = "rejected"
    store.save(rec)
    return jsonify({"ok": True, "deleted_count": 1})


def handle_memory_list():
    """List memory records."""
    ws_id = request.args.get("workspace_id", "")
    if not ws_id:
        return jsonify({"ok": False, "error": "workspace_id required"}), 400
    from workspace.memory_governance import MemoryStore
    store = MemoryStore()
    records = store.list_retrievable(ws_id)
    return jsonify({"ok": True, "records": records, "count": len(records)})
