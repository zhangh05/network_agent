# backend/api/memory.py
"""Memory API — status, write, search."""

from flask import request, jsonify
from backend.api.params import parse_limit
from memory.store import get_store
from memory.writer import write_memory
from memory.retriever import search_memory, list_memory


def handle_memory_status():
    """Return memory system status."""
    store = get_store()
    return jsonify({
        "enabled": True,
        "backend": "jsonl",
        "records": store.count(),
        "data_file": "memories.jsonl",
    })


def handle_memory_write():
    """Write a memory record via writer (redaction + policy enforced)."""
    data = request.get_json(silent=True) or {}
    if not data.get("title") and not data.get("content"):
        return jsonify({"ok": False, "error": "title or content required"}), 400

    confidence = data.get("confidence", "system_generated")
    user_confirmed = data.get("user_confirmed", confidence == "user_confirmed")

    memory_id = write_memory(
        title=data.get("title", ""),
        content=data.get("content", ""),
        scope=data.get("scope", "short_term"),
        memory_type=data.get("memory_type", "knowledge_note"),
        tags=data.get("tags", []),
        project_id=data.get("project_id", ""),
        source=data.get("source", "agent"),
        confidence=confidence,
        summary=data.get("summary", ""),
        sensitivity=data.get("sensitivity", "internal"),
        metadata=data.get("metadata"),
        user_confirmed=user_confirmed,
    )

    if not memory_id:
        return jsonify({"ok": False, "error": "Blocked by memory policy"}), 400

    record = get_store().get(memory_id)
    meta = record.metadata if record else {}
    return jsonify({
        "ok": True,
        "memory_id": memory_id,
        "conflict_detected": bool((meta or {}).get("conflict_detected")),
        "conflicts": list((meta or {}).get("conflicts") or []),
    })


def handle_memory_search():
    """Search memory with full filter support."""
    data = request.get_json(silent=True) or {}
    query = data.get("query", "")
    tags = data.get("tags", None)
    try:
        limit = parse_limit(data, default=10, max_value=100)
    except ValueError:
        return jsonify({"ok": False, "error": "invalid_limit"}), 400
    project_id = data.get("project_id", None)
    memory_type = data.get("memory_type", None)
    scope = data.get("scope", None)

    if not query and not any([tags, project_id, memory_type, scope]):
        return jsonify({"ok": False, "error": "query or at least one filter is required"}), 400

    results = search_memory(
        query=query, tags=tags, project_id=project_id,
        memory_type=memory_type, scope=scope, limit=limit,
    )
    return jsonify({"ok": True, "results": results, "count": len(results)})
