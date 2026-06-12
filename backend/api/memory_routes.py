# backend/api/memory_routes.py
"""Memory API routes — confirm, list, delete."""

from flask import request, jsonify
from backend.api.params import parse_limit
from memory.store import get_store
from memory.redaction import contains_secret
from memory.writer import (
    write_user_confirmed_decision,
    write_translation_rule,
    write_user_preference,
)


def handle_memory_confirm():
    """User-confirmed memory write for decision/rule/preference types."""
    data = request.get_json(silent=True) or {}
    memory_type = data.get("memory_type", "decision")
    title = data.get("title", "")
    content = data.get("content", "")
    tags = data.get("tags", [])
    project_id = data.get("project_id", "")

    if not content and not title:
        return jsonify({"ok": False, "error": "title or content required"}), 400

    # Pre-redaction check
    if contains_secret(content):
        return jsonify({
            "ok": False,
            "error": "Content contains secrets; redaction required",
        }), 400

    # Use convenience writers based on type
    if memory_type == "decision":
        mid = write_user_confirmed_decision(
            title=title, content=content,
            tags=tags, project_id=project_id,
        )
    elif memory_type == "translation_rule":
        mid = write_translation_rule(
            title=title, content=content,
            tags=tags, project_id=project_id,
        )
    elif memory_type == "user_preference":
        mid = write_user_preference(
            title=title, content=content,
            tags=tags, project_id=project_id,
        )
    else:
        # Generic user-confirmed write
        from memory.writer import write_memory
        mid = write_memory(
            title=title, content=content,
            scope="long_term", memory_type=memory_type,
            tags=tags, project_id=project_id,
            source="user", confidence="user_confirmed",
            sensitivity="internal", user_confirmed=True,
        )

    if not mid:
        return jsonify({"ok": False, "error": "Blocked by policy"}), 400

    return jsonify({
        "ok": True,
        "memory_id": mid,
        "redaction_applied": False,
    })


def handle_memory_delete(memory_id):
    """Tombstone-delete a memory record."""
    store = get_store()
    record = store.get(str(memory_id))
    ok = store.delete(str(memory_id))
    projection = {"ok": True, "deleted_count": 0}
    if ok:
        try:
            from memory.indexer import delete_memory_projection
            workspace_id = record.project_id if record else ""
            projection = delete_memory_projection(str(memory_id), workspace_id=workspace_id or "")
        except Exception as exc:
            projection = {"ok": False, "error": str(exc)[:160], "deleted_count": 0}
    return jsonify({"ok": ok, "rag_projection": projection})


def handle_memory_list():
    """List memory records with optional filters."""
    scope = request.args.get("scope")
    memory_type = request.args.get("memory_type")
    project_id = request.args.get("project_id")
    try:
        limit = parse_limit(request.args, default=100, max_value=500)
    except ValueError:
        return jsonify({"ok": False, "error": "invalid_limit"}), 400

    store = get_store()
    records = store.list(
        scope=scope, memory_type=memory_type,
        project_id=project_id, limit=limit,
    )

    # Ensure all records are dicts (for backward compat)
    clean = []
    for r in records:
        if isinstance(r, dict):
            clean.append(r)
        elif hasattr(r, 'as_dict'):
            clean.append(r.as_dict())
        else:
            clean.append({"title": str(r), "content": str(r)})

    return jsonify({
        "ok": True,
        "records": clean,
        "count": len(clean),
    })
