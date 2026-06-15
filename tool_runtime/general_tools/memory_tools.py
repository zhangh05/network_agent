"""Split general tool handlers."""
from tool_runtime.general_tools.shared import *

def handle_memory_search(inv: ToolInvocation) -> dict:
    query = (inv.arguments.get("query") or "").strip()
    try:
        from memory.backends.jsonl_store import JSONLMemoryStore
        store = JSONLMemoryStore()
        results = store.search(query, limit=10) if hasattr(store, 'search') else []
        safe = []
        for r in results:
            safe.append({
                "memory_id": r.get("memory_id", ""),
                "title": r.get("title", ""),
                "summary": (r.get("content", "") or "")[:200],
            })
        return _ok(inv, "", {"results": safe, "count": len(safe)})
    except Exception as e:
        return _error_inv(inv, str(e)[:200])

def handle_memory_create(inv: ToolInvocation) -> dict:
    """Create a long-term memory entry. Default status=pending_confirmation.

    Phase 2 enhancements: key, value_preview, status fields; session-scoped.
    """
    args = inv.arguments
    title = str(args.get("title", "")).strip()
    content = str(args.get("content", "")).strip()
    if not title or not content:
        return _error_inv(inv, "title and content are required")
    try:
        from memory.redaction import contains_secret, redact_text
        if contains_secret(title) or contains_secret(content):
            return _error_inv(inv, "content contains secrets — memory.create blocked")
        from memory.writer import write_memory
        import time
        key = str(args.get("key", title[:60]))
        value_preview = content[:200]
        ws = str(args.get("workspace_id", "default"))
        sid = str(args.get("session_id", ""))
        memory_id = write_memory(
            title=title,
            content=content,
            scope=str(args.get("scope", "long_term")),
            memory_type=str(args.get("memory_type", "knowledge_note")),
            tags=list(args.get("tags") or []),
            project_id=ws,
            source="llm_tool",
            confidence=str(args.get("confidence", "system_generated")),
            summary=str(args.get("summary", value_preview)),
            sensitivity=str(args.get("sensitivity", "internal")),
            metadata={
                **(args.get("metadata") or {}),
                "key": key,
                "value_preview": value_preview,
                "status": "pending_confirmation",
                "session_id": sid,
                "workspace_id": ws,
                "source": "llm_tool",
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            },
            user_confirmed=False,
        )
        if not memory_id:
            return _error_inv(inv, "memory write blocked by policy")
        return _ok(inv, "", {
            "memory_id": memory_id,
            "status": "pending_confirmation",
            "key": key,
            "value_preview": value_preview,
        })
    except Exception as e:
        return _error_inv(inv, str(e)[:200])

def handle_memory_list(inv: ToolInvocation) -> dict:
    """List memory entries. Phase 2: support status/session_id filtering, value_preview only."""
    args = inv.arguments
    try:
        from memory.backends.jsonl_store import JSONLMemoryStore
        store = JSONLMemoryStore()
        results = store.list(
            scope=args.get("scope"),
            memory_type=args.get("memory_type"),
            project_id=args.get("workspace_id"),
            limit=args.get("limit", 20),
        )
        # Phase 2 filtering
        status_filter = args.get("status", "")
        session_filter = args.get("session_id", "")
        include_deleted = bool(args.get("include_deleted", False))
        summaries = []
        for r in results:
            meta = (r.get("metadata") or {})
            mem_status = meta.get("status", "confirmed") if isinstance(meta, dict) else "confirmed"
            mem_sid = meta.get("session_id", "") if isinstance(meta, dict) else ""
            # Exclude deleted entries by default
            if mem_status == "deleted" and not include_deleted:
                continue
            if status_filter and mem_status != status_filter:
                continue
            if session_filter and mem_sid != session_filter:
                continue
            summaries.append({
                "memory_id": r.get("memory_id", ""),
                "title": r.get("title", ""),
                "summary": (r.get("summary", "") or r.get("content", ""))[:200],
                "key": meta.get("key", "") if isinstance(meta, dict) else "",
                "value_preview": meta.get("value_preview", "") if isinstance(meta, dict) else "",
                "status": mem_status,
                "memory_type": r.get("memory_type", ""),
                "scope": r.get("scope", ""),
                "created_at": r.get("created_at", ""),
                "tags": r.get("tags", [])[:5],
            })
        return _ok(inv, "", {"results": summaries, "count": len(summaries)})
    except Exception as e:
        return _error_inv(inv, str(e)[:200])

def handle_memory_confirm(inv: ToolInvocation) -> dict:
    """Confirm a pending_confirmation memory entry.

    Updates the in-store status to 'confirmed'. Does not rebuild RAG index —
    no project_to_knowledge / _update_rag function exists in memory/writer.py.
    If such a projection is added in the future, it should be called best-effort
    after the status update below.
    """
    args = inv.arguments
    memory_id = str(args.get("memory_id", "")).strip()
    if not memory_id:
        return _error_inv(inv, "memory_id is required")
    try:
        from memory.backends.jsonl_store import JSONLMemoryStore
        store = JSONLMemoryStore()
        entry = store.get(memory_id)
        if not entry:
            return _error_inv(inv, f"memory_id not found: {memory_id}")

        meta = entry.get("metadata") or {}
        status = meta.get("status", "confirmed") if isinstance(meta, dict) else "confirmed"
        if status == "confirmed":
            return _ok(inv, "", {"memory_id": memory_id, "already_confirmed": True, "status": "confirmed"})

        # Update status
        if isinstance(meta, dict):
            meta["status"] = "confirmed"
        else:
            meta = {"status": "confirmed"}
        store.update_metadata(memory_id, meta)

        # Best-effort RAG projection (documented: no project_to_knowledge yet)
        # try:
        #     from memory.writer import project_to_knowledge
        #     content = entry.get("content", "")
        #     if content:
        #         project_to_knowledge(memory_id, content)
        # except Exception:
        #     pass

        return _ok(inv, "", {"memory_id": memory_id, "status": "confirmed", "already_confirmed": False})
    except Exception as e:
        return _error_inv(inv, str(e)[:200])

def handle_memory_get_profile(inv: ToolInvocation) -> dict:
    """Get user profile. Phase 2: returns explicit/implicit/tool_stats/updated_at."""
    ws = inv.arguments.get("workspace_id", "default")
    try:
        validate_workspace_id(ws)
        profile_path = WS_ROOT / ws / "memory" / "profile.json"
        if not profile_path.is_file():
            return _ok(inv, "", {
                "explicit_preferences": {},
                "inferred_preferences": {},
                "tool_usage_stats": {},
                "updated_at": "",
            })
        import json
        data = json.loads(profile_path.read_text(encoding="utf-8"))
        return _ok(inv, "", {
            "explicit_preferences": data.get("explicit_preferences", {}),
            "inferred_preferences": data.get("inferred_preferences", {}),
            "tool_usage_stats": data.get("tool_usage_stats", {}),
            "updated_at": data.get("updated_at", ""),
        })
    except Exception as e:
        return _error_inv(inv, str(e)[:200])

def handle_memory_set_profile(inv: ToolInvocation) -> dict:
    """Set user profile. Phase 2: merge=false replaces; merge=true (default) merges into explicit_preferences.

    Only writes to explicit_preferences. Never stores secrets.
    """
    ws = inv.arguments.get("workspace_id", "default")
    field = str(inv.arguments.get("field", "")).strip()
    value = inv.arguments.get("value")
    merge = bool(args.get("merge", True)) if (args := inv.arguments) else True
    if not field:
        return _error_inv(inv, "field is required")
    try:
        validate_workspace_id(ws)
        from memory.redaction import contains_secret
        if isinstance(value, str) and contains_secret(value):
            return _error_inv(inv, "value contains secrets — set_profile blocked")
        import json, time
        memory_dir = WS_ROOT / ws / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        profile_path = memory_dir / "profile.json"
        profile = {"explicit_preferences": {}, "inferred_preferences": {}, "tool_usage_stats": {}, "updated_at": ""}
        if profile_path.is_file():
            existing = json.loads(profile_path.read_text(encoding="utf-8"))
            profile.update(existing)
        if merge:
            profile.setdefault("explicit_preferences", {})[field] = value
        else:
            profile["explicit_preferences"] = {field: value} if value is not None else {}
        profile["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
        return _ok(inv, "", {"field": field, "saved": True})
    except Exception as e:
        return _error_inv(inv, str(e)[:200])

def handle_memory_update(inv: ToolInvocation) -> dict:
    """Update an existing memory entry's content field directly (not just metadata)."""
    args = inv.arguments
    memory_id = str(args.get("memory_id", "")).strip()
    content = str(args.get("content", "")).strip()
    if not memory_id:
        return _error_inv(inv, "memory_id is required")
    if not content:
        return _error_inv(inv, "content is required")
    try:
        from memory.redaction import contains_secret
        if contains_secret(content):
            return _error_inv(inv, "content contains secrets — memory.update blocked")
        from memory.backends.jsonl_store import JSONLMemoryStore
        store = JSONLMemoryStore()
        entry = store.get(memory_id)
        if not entry:
            return _error_inv(inv, f"memory_id not found: {memory_id}")
        # Update the actual content field, not just metadata
        entry["content"] = content
        # Also update metadata timestamp
        meta = (entry.get("metadata") or {})
        if not isinstance(meta, dict):
            meta = {}
        meta["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        meta["status"] = "updated"
        entry["metadata"] = meta
        store.update_metadata(memory_id, meta)
        return _ok(inv, "", {"memory_id": memory_id, "updated": True})
    except Exception as e:
        return _error_inv(inv, str(e)[:200])

def handle_memory_delete_soft(inv: ToolInvocation) -> dict:
    """Soft-delete a memory entry. Marks as deleted, does not remove from store."""
    args = inv.arguments
    memory_id = str(args.get("memory_id", "")).strip()
    if not memory_id:
        return _error_inv(inv, "memory_id is required")
    try:
        from memory.backends.jsonl_store import JSONLMemoryStore
        store = JSONLMemoryStore()
        entry = store.get(memory_id)
        if not entry:
            return _error_inv(inv, f"memory_id not found: {memory_id}")
        meta = (entry.get("metadata") or {})
        if not isinstance(meta, dict):
            meta = {}
        meta["status"] = "deleted"
        meta["deleted_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        store.update_metadata(memory_id, meta)
        return _ok(inv, "", {"memory_id": memory_id, "deleted": True})
    except Exception as e:
        return _error_inv(inv, str(e)[:200])

__all__ = ['handle_memory_search', 'handle_memory_create', 'handle_memory_list', 'handle_memory_confirm', 'handle_memory_get_profile', 'handle_memory_set_profile', 'handle_memory_update', 'handle_memory_delete_soft']
