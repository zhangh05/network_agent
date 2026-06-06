# backend/api/memory_routes.py
"""Memory API routes — confirm, list, delete."""

from flask import request, jsonify
from memory.schemas import MemoryRecord
from memory.backends.jsonl_store import JSONLMemoryStore
from memory.policy import can_write_memory
from memory.redaction import redact_text, contains_secret


def handle_memory_confirm():
    data = request.get_json(silent=True) or {}
    memory_type = data.get("memory_type", "decision")
    title = data.get("title", "")
    content = data.get("content", "")
    tags = data.get("tags", [])
    project_id = data.get("project_id")

    if contains_secret(content):
        return jsonify({"ok": False, "error": "Content contains secrets; redaction required"}), 400

    policy = can_write_memory(memory_type, content, "user_confirmed")
    if not policy.allowed:
        return jsonify({"ok": False, "error": policy.reason}), 400

    record = MemoryRecord(
        memory_type=memory_type, scope="long_term",
        title=title, content=content, tags=tags,
        project_id=project_id, confidence="user_confirmed",
        sensitivity="internal", source="user_confirmed",
    )
    store = JSONLMemoryStore()
    rid = store.put(record)
    return jsonify({"ok": True, "memory_id": rid, "redaction_applied": policy.redaction_needed})


def handle_memory_delete(memory_id):
    store = JSONLMemoryStore()
    ok = store.delete(str(memory_id))
    return jsonify({"ok": ok})


def handle_memory_list():
    store = JSONLMemoryStore()
    records = []
    for r in store.list():
        if hasattr(r, 'as_dict'):
            records.append(r.as_dict())
        elif isinstance(r, dict):
            records.append(r)
        else:
            records.append({"title": str(r), "content": str(r)})
    return jsonify({
        "ok": True,
        "records": records,
        "count": len(records),
    })
