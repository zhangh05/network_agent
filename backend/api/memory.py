# backend/api/memory.py
"""Memory API — status, write, search.
v3.10: ALL memory operations now go through workspace/memory_governance.py.
Old memory.store / memory.writer / memory.retriever are deprecated.
    MemoryWriteGate enforces: redaction, secret rejection, pending/active, conflict detection.
."""
from flask import request, jsonify


def _validated_ws_id(raw: str) -> str:
    """Validate and return workspace_id. Empty → 400."""
    if not raw or not raw.strip():
        return ""
    return raw.strip()


def handle_memory_status():
    """Return memory system status for the given workspace."""
    ws_id = request.args.get("workspace_id", "")
    ws_id = _validated_ws_id(ws_id)
    if not ws_id:
        return jsonify({"ok": False, "error": "workspace_id is required"}), 400
    try:
        from workspace.memory_governance import MemoryStore, MemoryWriteGate
        store = MemoryStore()
        gate = MemoryWriteGate()
        records = store.list_retrievable(ws_id)
        return jsonify({
            "ok": True,
            "enabled": True,
            "backend": "governed_context_store",
            "workspace_id": ws_id,
            "records": len(records),
            "data_dir": f"workspaces/{ws_id}/durable/memory/",
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


def handle_memory_write():
    """Write a memory record through MemoryWriteGate (governed)."""
    data = request.get_json(silent=True) or {}
    title = data.get("title", "")
    content = data.get("content", "")
    if not title and not content:
        return jsonify({"ok": False, "error": "title or content required"}), 400

    workspace_id = data.get("workspace_id", "")
    ws_id = _validated_ws_id(workspace_id)
    if not ws_id:
        return jsonify({"ok": False, "error": "workspace_id is required"}), 400

    source = data.get("source", "agent")
    confidence = float(data.get("confidence", 0.5))
    user_confirmed = data.get("user_confirmed", False)
    is_subagent = bool(data.get("is_subagent", False))

    try:
        from workspace.memory_governance import MemoryRecord, MemoryWriteGate
        gate = MemoryWriteGate()

        # Build MemoryRecord for governance
        rec = MemoryRecord(
            workspace_id=ws_id,
            session_id=data.get("session_id", ""),
            task_id=data.get("task_id", ""),
            scope=data.get("scope", "workspace"),
            memory_type=data.get("memory_type", "operational_fact"),
            status="pending",
            source="user" if user_confirmed else ("subagent" if is_subagent else "agent_suggestion"),
            content=content[:2000],
            summary=title[:200],
            confidence=confidence,
            citations=data.get("citations", []),
            created_by=source,
            redacted=True,
        )

        result = gate.write(rec)
        return jsonify(result)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


def handle_memory_search():
    """Search memory records through MemoryStore (governed)."""
    data = request.get_json(silent=True) or {}
    query = data.get("query", "")
    workspace_id = data.get("workspace_id", "")
    ws_id = _validated_ws_id(workspace_id)
    if not ws_id:
        return jsonify({"ok": False, "error": "workspace_id is required"}), 400

    try:
        limit = min(int(data.get("limit", 10)), 100)
    except (ValueError, TypeError):
        return jsonify({"ok": False, "error": "invalid_limit"}), 400

    try:
        from workspace.memory_governance import MemoryStore
        store = MemoryStore()
        records = store.list_retrievable(ws_id, limit=limit)

        # Filter by query text if provided
        if query:
            q = query.lower()
            records = [r for r in records if q in (r.get("content","")+r.get("summary","")).lower()]

        return jsonify({"ok": True, "results": records[:limit], "count": len(records[:limit])})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


def handle_memory_confirm():
    """Confirm a pending memory record."""
    data = request.get_json(silent=True) or {}
    ws_id = _validated_ws_id(data.get("workspace_id", ""))
    memory_id = data.get("memory_id", "")
    if not ws_id or not memory_id:
        return jsonify({"ok": False, "error": "workspace_id and memory_id required"}), 400

    try:
        from workspace.memory_governance import confirm_memory
        result = confirm_memory(ws_id, memory_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500


def handle_memory_reject():
    """Reject a pending memory record."""
    data = request.get_json(silent=True) or {}
    ws_id = _validated_ws_id(data.get("workspace_id", ""))
    memory_id = data.get("memory_id", "")
    if not ws_id or not memory_id:
        return jsonify({"ok": False, "error": "workspace_id and memory_id required"}), 400

    try:
        from workspace.memory_governance import reject_memory
        result = reject_memory(ws_id, memory_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:200]}), 500
