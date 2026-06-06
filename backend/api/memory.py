# backend/api/memory.py

from flask import request, jsonify

from memory.store import get_store
from memory.writer import write_memory
from memory.retriever import search_memory, list_memory


def handle_memory_status():
    store = get_store()
    return jsonify({
        "enabled": True,
        "backend": "jsonl",
        "records": store.count(),
    })


def handle_memory_write():
    data = request.get_json(silent=True) or {}
    if not data.get("title") and not data.get("content"):
        return jsonify({"ok": False, "error": "title or content required"}), 400

    memory_id = write_memory(
        title=data.get("title", ""),
        content=data.get("content", ""),
        scope=data.get("scope", "short_term"),
        memory_type=data.get("memory_type", "knowledge_note"),
        tags=data.get("tags", []),
        project_id=data.get("project_id", ""),
        source=data.get("source", "agent"),
        confidence=data.get("confidence", 0.8),
        summary=data.get("summary", ""),
    )
    return jsonify({"ok": True, "memory_id": memory_id})


def handle_memory_search():
    data = request.get_json(silent=True) or {}
    query = data.get("query", "")
    tags = data.get("tags", None)
    limit = int(data.get("limit", 10))
    scope = data.get("scope", None)

    if not query:
        return jsonify({"ok": False, "error": "query required"}), 400

    results = search_memory(query=query, tags=tags, limit=limit)
    return jsonify({"ok": True, "results": results, "count": len(results)})
