"""Memory tool handlers — uses unified ContextStore.

v3.1.0: All operations go through memory.store (ContextStoreAdapter)
and context.context_store (ContextStore). No legacy JSONL backends.
"""
from tool_runtime.general_tools.shared import *


def _caller_workspace(inv: ToolInvocation) -> str:
    requested = str(inv.arguments.get("workspace_id") or "").strip()
    caller = str(inv.workspace_id or "").strip()
    if caller and requested and caller != requested:
        raise ValueError(
            f"workspace_id mismatch: caller={caller!r}, requested={requested!r}"
        )
    workspace_id = caller or requested or "default"
    validate_workspace_id(workspace_id)
    return workspace_id


def handle_memory_search(inv: ToolInvocation) -> dict:
    query = (inv.arguments.get("query") or "").strip()
    try:
        from memory.store import get_store
        store = get_store(_caller_workspace(inv))
        results = store.search(query, limit=10)
        safe = []
        for r in results:
            safe.append({
                "memory_id": r.get("memory_id", r.get("item_id", "")),
                "title": r.get("title", ""),
                "summary": (r.get("content", "") or "")[:200],
            })
        return _ok(inv, "", {"results": safe, "count": len(safe)})
    except Exception as e:
        return _error_inv(inv, str(e)[:200])


def handle_memory_create(inv: ToolInvocation) -> dict:
    args = inv.arguments
    title = str(args.get("title", "")).strip()
    content = str(args.get("content", "")).strip()
    if not title or not content:
        return _error_inv(inv, "title and content are required")
    try:
        from memory.redaction import contains_secret
        if contains_secret(title) or contains_secret(content):
            return _error_inv(inv, "content contains secrets — memory.create blocked")
        from memory.writer import write_memory
        import time
        key = str(args.get("key", title[:60]))
        value_preview = content[:200]
        ws = _caller_workspace(inv)
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
    args = inv.arguments
    try:
        from memory.store import get_store
        ws = _caller_workspace(inv)
        store = get_store(ws)
        results = store.list(
            scope=args.get("scope"),
            memory_type=args.get("memory_type"),
            project_id=ws,
            limit=args.get("limit", 20),
        )
        status_filter = args.get("status", "")
        session_filter = args.get("session_id", "")
        include_deleted = bool(args.get("include_deleted", False))
        summaries = []
        for r in results:
            meta = (r.get("metadata") or {})
            mem_status = meta.get("status", "confirmed") if isinstance(meta, dict) else "confirmed"
            mem_sid = meta.get("session_id", "") if isinstance(meta, dict) else ""
            if mem_status == "deleted" and not include_deleted:
                continue
            if status_filter and mem_status != status_filter:
                continue
            if session_filter and mem_sid != session_filter:
                continue
            summaries.append({
                "memory_id": r.get("memory_id", r.get("item_id", "")),
                "title": r.get("title", ""),
                "summary": (r.get("summary", "") or r.get("content", ""))[:200],
                "key": meta.get("key", "") if isinstance(meta, dict) else "",
                "value_preview": meta.get("value_preview", "") if isinstance(meta, dict) else "",
                "status": mem_status,
                "memory_type": r.get("memory_type", ""),
                "scope": r.get("scope", ""),
                "created_at": r.get("created_at", ""),
                "tags": (r.get("tags") or [])[:5],
            })
        return _ok(inv, "", {"results": summaries, "count": len(summaries)})
    except Exception as e:
        return _error_inv(inv, str(e)[:200])


def handle_memory_confirm(inv: ToolInvocation) -> dict:
    args = inv.arguments
    memory_id = str(args.get("memory_id", "")).strip()
    if not memory_id:
        return _error_inv(inv, "memory_id is required")
    try:
        # P0 fix (round 7): use the caller's workspace, not hardcoded "default".
        # Cross-workspace data access is a privilege boundary.
        from context.context_store import get_context_store
        ws = _caller_workspace(inv)
        store = get_context_store(ws)
        entry = store.get(memory_id)
        if not entry:
            return _error_inv(inv, f"memory_id not found: {memory_id}")

        meta = entry.get("metadata") or {}
        status = meta.get("status", "confirmed") if isinstance(meta, dict) else "confirmed"
        if status == "confirmed":
            return _ok(inv, "", {"memory_id": memory_id, "already_confirmed": True, "status": "confirmed"})

        if isinstance(meta, dict):
            meta["status"] = "confirmed"
        else:
            meta = {"status": "confirmed"}
        entry["metadata"] = meta
        store.put(entry)

        return _ok(inv, "", {"memory_id": memory_id, "status": "confirmed", "already_confirmed": False})
    except Exception as e:
        return _error_inv(inv, str(e)[:200])


def handle_memory_get_profile(inv: ToolInvocation) -> dict:
    try:
        ws = _caller_workspace(inv)
        from context.context_store import get_context_store
        store = get_context_store(ws)
        items = store.list_items(item_type="profile", limit=1)
        if not items:
            return _ok(inv, "No profile found; returning empty default.", {
                "explicit_preferences": {},
                "inferred_preferences": {},
                "tool_usage_stats": {},
                "updated_at": "",
                "warnings": ["tool_returned_no_payload"],
            })
        data = items[0].get("content", {})
        if isinstance(data, str):
            import json
            try:
                data = json.loads(data)
            except Exception:
                data = {}
        payload = {
            "explicit_preferences": data.get("explicit_preferences", {}),
            "inferred_preferences": data.get("inferred_preferences", {}),
            "tool_usage_stats": data.get("tool_usage_stats", {}),
            "updated_at": data.get("updated_at", ""),
        }
        if not any(v not in (None, "", [], {}) for v in payload.values()):
            payload["warnings"] = ["tool_returned_no_payload"]
        return _ok(inv, "Profile loaded.", payload)
    except Exception as e:
        return _error_inv(inv, str(e)[:200])


def handle_memory_set_profile(inv: ToolInvocation) -> dict:
    field = str(inv.arguments.get("field", "")).strip()
    value = inv.arguments.get("value")
    merge = bool(inv.arguments.get("merge", True))
    if not field:
        return _error_inv(inv, "field is required")
    try:
        ws = _caller_workspace(inv)
        from memory.redaction import contains_secret
        if isinstance(value, str) and contains_secret(value):
            return _error_inv(inv, "value contains secrets — set_profile blocked")
        import time
        from context.context_store import get_context_store
        store = get_context_store(ws)
        items = store.list_items(item_type="profile", limit=1)
        profile = {"explicit_preferences": {}, "inferred_preferences": {}, "tool_usage_stats": {}, "updated_at": ""}
        if items:
            existing = items[0].get("content", {})
            if isinstance(existing, dict):
                profile.update(existing)
        if merge:
            profile.setdefault("explicit_preferences", {})[field] = value
        else:
            profile["explicit_preferences"] = {field: value} if value is not None else {}
        profile["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

        item = {
            "item_id": f"profile_{ws}",
            "item_type": "profile",
            "source": "user_tool",
            "title": "User Profile",
            "summary": f"Updated: {field}",
            "content": profile,
            "scope": "workspace",
        }
        store.put(item)
        return _ok(inv, "", {"field": field, "saved": True})
    except Exception as e:
        return _error_inv(inv, str(e)[:200])


def handle_memory_update(inv: ToolInvocation) -> dict:
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
        import time
        # P0 fix (round 7): use caller's workspace instead of hardcoded "default"
        # to enforce workspace isolation.
        from context.context_store import get_context_store
        ws = _caller_workspace(inv)
        store = get_context_store(ws)
        entry = store.get(memory_id)
        if not entry:
            return _error_inv(inv, f"memory_id not found: {memory_id}")
        entry["content"] = content
        meta = entry.get("metadata") or {}
        if not isinstance(meta, dict):
            meta = {}
        meta["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        meta["status"] = "updated"
        entry["metadata"] = meta
        store.put(entry)
        return _ok(inv, "", {"memory_id": memory_id, "updated": True})
    except Exception as e:
        return _error_inv(inv, str(e)[:200])


def handle_memory_delete_soft(inv: ToolInvocation) -> dict:
    args = inv.arguments
    memory_id = str(args.get("memory_id", "")).strip()
    if not memory_id:
        return _error_inv(inv, "memory_id is required")
    try:
        # P0 fix (round 7): enforce workspace isolation; do not let one
        # workspace's LLM delete another workspace's memory.
        from context.context_store import get_context_store
        ws = _caller_workspace(inv)
        store = get_context_store(ws)
        entry = store.get(memory_id)
        if not entry:
            return _error_inv(inv, f"memory_id not found: {memory_id}")
        store.delete(memory_id)
        return _ok(inv, "", {"memory_id": memory_id, "deleted": True})
    except Exception as e:
        return _error_inv(inv, str(e)[:200])


__all__ = ['handle_memory_search', 'handle_memory_create', 'handle_memory_list',
           'handle_memory_confirm', 'handle_memory_get_profile', 'handle_memory_set_profile',
           'handle_memory_update', 'handle_memory_delete_soft']
