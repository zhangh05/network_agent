"""Memory tool handlers — v3.10 governed MemoryWriteGate/MemoryStore path."""

from tool_runtime.schemas import ToolInvocation

from tool_runtime.general_tools.shared import _error_inv, _ok
from workspace.ids import validate_workspace_id
from agent.runtime.utils import now_iso


def _caller_workspace(inv: ToolInvocation) -> str:
    """Extract validated workspace_id from caller context. No default fallback."""
    requested = str(inv.arguments.get("workspace_id") or "").strip()
    caller = str(inv.workspace_id or "").strip()
    if caller and requested and caller != requested:
        raise ValueError(f"workspace_id mismatch: caller={caller!r}, requested={requested!r}")
    workspace_id = caller or requested or ""
    if not workspace_id:
        raise ValueError("workspace_id is required — no default fallback")
    validate_workspace_id(workspace_id)
    return workspace_id


def _get_store(ws_id: str):
    from workspace.memory_governance import MemoryStore
    return MemoryStore()


def _via_gate(title: str, content: str, ws_id: str, source: str = "llm_tool",
              memory_type: str = "knowledge_note", scope: str = "workspace",
              session_id: str = "", task_id: str = "", user_confirmed: bool = False,
              citations: list = None, tags: list = None) -> dict:
    """Write memory through MemoryWriteGate (governed path only)."""
    from workspace.memory_governance import MemoryRecord, MemoryWriteGate
    rec = MemoryRecord(
        workspace_id=ws_id, session_id=session_id, task_id=task_id,
        scope=scope, memory_type=memory_type,
        status="active" if user_confirmed else "pending",
        source="user" if user_confirmed else ("subagent" if source == "subagent" else "agent_suggestion"),
        content=content[:2000], summary=title[:200],
        confidence=1.0 if user_confirmed else 0.5,
        citations=citations or [], created_by=source,
        redacted=True,
    )
    gate = MemoryWriteGate()
    from workspace.memory_governance import get_memory_gate_mode
    gate_mode = get_memory_gate_mode(ws_id)
    return gate.write(rec, gate_mode=gate_mode)


def handle_memory_search(inv: ToolInvocation) -> dict:
    query = (inv.arguments.get("query") or "").strip()
    try:
        ws = _caller_workspace(inv)
        store = _get_store(ws)
        results = store.list_retrievable(ws, limit=10)
        if query:
            q = query.lower()
            results = [r for r in results if q in (r.get("content", "") + r.get("summary", "")).lower()]
        safe = [{
            "memory_id": r.get("memory_id", ""),
            "title": r.get("title", ""),
            "summary": r.get("summary", "")[:200],
        } for r in results]
        return _ok(inv, "", {"results": safe, "count": len(safe)})
    except Exception as e:
        return _error_inv(inv, str(e)[:200])


def handle_memory_create(inv: ToolInvocation) -> dict:
    args = inv.arguments
    title = str(args.get("title", "")).strip()
    content = str(args.get("content", "")).strip()
    if not content:
        return _error_inv(inv, "content is required")
    if not title:
        title = str(args.get("summary", "")).strip() or content[:80]
    try:
        ws = _caller_workspace(inv)
        sid = str(args.get("session_id", ""))
        is_sub = bool(args.get("is_subagent", False))
        source = "subagent" if is_sub else "llm_tool"
        result = _via_gate(
            title=title, content=content, ws_id=ws,
            source=source,
            memory_type=str(args.get("memory_type", "knowledge_note")),
            scope=str(args.get("scope", "workspace")),
            session_id=sid,
            user_confirmed=bool(args.get("user_confirmed", False)),
            tags=list(args.get("tags") or []),
        )
        memory_id = result.get("memory_id", "")
        if not memory_id:
            return _error_inv(inv, "memory write blocked by policy")
        if result.get("rejected"):
            return _error_inv(inv, f"memory rejected: {result.get('summary', 'secret content')}")
        return _ok(inv, "", {
            "memory_id": memory_id,
            "status": result.get("status", "pending"),
        })
    except Exception as e:
        return _error_inv(inv, str(e)[:200])


def handle_memory_list(inv: ToolInvocation) -> dict:
    args = inv.arguments
    try:
        ws = _caller_workspace(inv)
        store = _get_store(ws)
        results = store.list_retrievable(ws, limit=int(args.get("limit", 20)))
        session_filter = args.get("session_id", "")
        summaries = []
        for r in results:
            if session_filter and r.get("session_id", "") != session_filter:
                continue
            summaries.append({
                "memory_id": r.get("memory_id", ""),
                "title": r.get("title", ""),
                "summary": r.get("summary", "")[:200],
                "status": r.get("status", "confirmed"),
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
        ws = _caller_workspace(inv)
        from workspace.memory_governance import confirm_memory
        result = confirm_memory(ws, memory_id)
        return _ok(inv, "", {"memory_id": memory_id, **result})
    except Exception as e:
        return _error_inv(inv, str(e)[:200])


def handle_memory_get_profile(inv: ToolInvocation) -> dict:
    try:
        ws = _caller_workspace(inv)
        store = _get_store(ws)
        results = store.list_retrievable(ws, memory_type="profile", limit=1)
        if not results:
            return _ok(inv, "No profile found", {
                "explicit_preferences": {},
                "inferred_preferences": {},
                "tool_usage_stats": {},
                "updated_at": "",
                "warnings": ["tool_returned_no_payload"],
            })
        data = results[0]
        return _ok(inv, "Profile loaded.", {
            "explicit_preferences": data.get("explicit_preferences", {}),
            "inferred_preferences": data.get("inferred_preferences", {}),
            "tool_usage_stats": data.get("tool_usage_stats", {}),
            "updated_at": data.get("updated_at", ""),
        })
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
        import time
        # Build profile content as memory record
        from workspace.memory_governance import MemoryRecord, MemoryWriteGate
        existing = {}
        store = _get_store(ws)
        results = store.list_retrievable(ws, memory_type="profile", limit=1)
        if results:
            existing = results[0]
        profile = existing if existing else {"explicit_preferences": {}, "inferred_preferences": {}, "updated_at": ""}
        if merge and isinstance(profile.get("explicit_preferences"), dict):
            profile["explicit_preferences"][field] = value
        else:
            profile["explicit_preferences"] = {field: value}
        profile["updated_at"] = now_iso()

        rec = MemoryRecord(
            workspace_id=ws, scope="workspace",
            memory_type="profile", status="active",
            source="user", content=str(profile)[:2000],
            summary=f"Profile updated: {field}",
            confidence=1.0, created_by="user", redacted=True,
        )
        gate = MemoryWriteGate()
        gate.write(rec)
        return _ok(inv, "", {"field": field, "saved": True})
    except Exception as e:
        return _error_inv(inv, str(e)[:200])


def handle_memory_search_merged(inv: ToolInvocation) -> dict:
    """Merged handler for memory.manage(action=search|list)."""
    if inv.arguments.get("query", "").strip():
        return handle_memory_search(inv)
    return handle_memory_list(inv)


def handle_memory_profile_merged(inv: ToolInvocation) -> dict:
    """Merged handler for memory.manage(action=profile_get|profile_set)."""
    if inv.arguments.get("field", "").strip():
        return handle_memory_set_profile(inv)
    return handle_memory_get_profile(inv)


def handle_memory_update(inv: ToolInvocation) -> dict:
    args = inv.arguments
    memory_id = str(args.get("memory_id", "")).strip()
    content = str(args.get("content", "")).strip()
    if not memory_id:
        return _error_inv(inv, "memory_id is required")
    if not content:
        return _error_inv(inv, "content is required")
    try:
        ws = _caller_workspace(inv)
        store = _get_store(ws)
        rec = store.get(ws, memory_id)
        if not rec:
            return _error_inv(inv, f"memory_id not found: {memory_id}")
        rec.content = content[:2000]
        import time
        rec.updated_at = now_iso()
        from workspace.memory_governance import MemoryWriteGate
        gate = MemoryWriteGate()
        result = gate.write(rec)
        if not result.get("ok", False):
            return _error_inv(inv, result.get("rejected") or result.get("error", "gate rejected update"))
        return _ok(inv, "", {"memory_id": memory_id, "updated": True})
    except Exception as e:
        return _error_inv(inv, str(e)[:200])


def handle_memory_delete_soft(inv: ToolInvocation) -> dict:
    args = inv.arguments
    memory_id = str(args.get("memory_id", "")).strip()
    if not memory_id:
        return _error_inv(inv, "memory_id is required")
    try:
        ws = _caller_workspace(inv)
        from workspace.memory_governance import reject_memory
        result = reject_memory(ws, memory_id)
        return _ok(inv, "", {"memory_id": memory_id, "deleted": True, **result})
    except Exception as e:
        return _error_inv(inv, str(e)[:200])
