"""Session store — manage conversation sessions per workspace.

A Session is a conversation thread that groups multiple runs.
Sessions support soft-delete / archive semantics: deleting a session
only marks it as deleted; run records and artifacts remain intact
for audit purposes.
"""

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from workspace.ids import validate_workspace_id
from workspace.manager import ensure_workspace

ROOT = Path(__file__).resolve().parent.parent
WS_ROOT = ROOT / "workspaces"


def _session_dir(ws_id: str) -> Path:
    """Return the sessions directory for a workspace."""
    return WS_ROOT / ws_id / "sessions"


def _session_path(session_id: str, ws_id: str) -> Path:
    """Return the file path for a session record. Validates session_id to prevent path traversal."""
    # Validate session_id: only allow alphanumeric + underscore + hyphen
    safe_id = re.sub(r'[^a-zA-Z0-9_-]', '', str(session_id))
    if safe_id != str(session_id) or not safe_id:
        raise ValueError(f"Invalid session_id: {session_id}")
    return _session_dir(ws_id) / f"{safe_id}.json"


def _now_iso() -> str:
    """Return current UTC time in ISO format."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# ─── Session CRUD ───


def create_session(
    ws_id: str = "default",
    title: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create a new session. Returns the session dict."""
    ws_id = ensure_workspace(ws_id)
    _session_dir(ws_id).mkdir(parents=True, exist_ok=True)

    session_id = uuid.uuid4().hex[:16]
    now = _now_iso()
    session = {
        "session_id": session_id,
        "workspace_id": ws_id,
        "title": title or "新会话",
        "status": "active",
        "created_at": now,
        "updated_at": now,
        "run_ids": [],
        "metadata": metadata or {},
    }
    _write_session(session, ws_id)
    return session


def get_session(session_id: str, ws_id: str = "default") -> Optional[Dict[str, Any]]:
    """Get a single session by ID."""
    ws_id = validate_workspace_id(ws_id)
    path = _session_path(session_id, ws_id)
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None


def list_sessions(
    ws_id: str = "default",
    status: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """List sessions for a workspace.

    Args:
        ws_id: Workspace ID.
        status: Filter by status ('active', 'archived', 'deleted').
                None means include all non-deleted (active + archived).
        limit: Max number of sessions to return.

    v3.1.1: Auto-repairs orphaned session directories (messages on disk
    but no JSON metadata) by synthesizing minimal session metadata.
    """
    ws_id = ensure_workspace(ws_id)
    sdir = _session_dir(ws_id)
    if not sdir.is_dir():
        return []

    sessions = []
    seen_ids = set()

    for f in sdir.glob("*.json"):
        try:
            s = json.loads(f.read_text(encoding="utf-8"))
            sessions.append(s)
            seen_ids.add(s.get("session_id", f.stem))
        except Exception:
            pass

    # v3.1.1: Auto-repair orphaned sessions (directories with messages but no .json)
    for item in sdir.iterdir():
        if not item.is_dir():
            continue
        sid = item.name
        if sid in seen_ids:
            continue
        msg_dir = item / "messages"
        if not msg_dir.is_dir():
            continue
        try:
            msgs = sorted(msg_dir.iterdir())
            if not msgs:
                continue
            # Derive title from first user message
            title = sid
            first_ts = _now_iso()
            for mf in msgs:
                if mf.name.endswith(":user.json"):
                    try:
                        data = json.loads(mf.read_text(encoding="utf-8"))
                        content = data.get("content", "")
                        if content:
                            title = content[:60].replace("\n", " ")
                        first_ts = data.get("timestamp", first_ts)
                    except Exception:
                        pass
                    break
            session_data = {
                "session_id": sid, "workspace_id": ws_id,
                "title": title, "status": "active",
                "created_at": first_ts, "updated_at": first_ts,
                "run_ids": [], "metadata": {"auto_repaired": True},
            }
            _write_session(session_data, ws_id)
            sessions.append(session_data)
            seen_ids.add(sid)
        except Exception:
            pass

    # Default filter: exclude deleted
    if status is None:
        sessions = [s for s in sessions if s.get("status") != "deleted"]
    else:
        sessions = [s for s in sessions if s.get("status") == status]

    # Sort by updated_at desc
    sessions.sort(key=lambda s: s.get("updated_at", ""), reverse=True)
    return sessions[:limit]


def update_session(
    session_id: str,
    ws_id: str = "default",
    title: Optional[str] = None,
    status: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Update session fields. Returns updated session or None if not found."""
    ws_id = validate_workspace_id(ws_id)
    session = get_session(session_id, ws_id)
    if not session:
        return None

    if title is not None:
        session["title"] = title
    if status is not None:
        if status in ("active", "archived", "deleted"):
            session["status"] = status
    if metadata is not None:
        session["metadata"] = metadata

    session["updated_at"] = _now_iso()
    _write_session(session, ws_id)
    return session


def archive_session(session_id: str, ws_id: str = "default") -> Optional[Dict[str, Any]]:
    """Soft-archive a session (status → 'archived')."""
    return update_session(session_id, ws_id, status="archived")


def soft_delete_session(session_id: str, ws_id: str = "default") -> Optional[Dict[str, Any]]:
    """Soft-delete a session (status → 'deleted'). Run records are preserved."""
    return update_session(session_id, ws_id, status="deleted")


def delete_session_permanently(
    session_id: str, ws_id: str = "default", confirm: bool = False
) -> bool:
    """Physically delete the session and its messages.

    Removes both the JSON metadata file and the messages/ directory
    so that list_sessions' auto-repair does not resurrect the session.

    Requires confirm=True as a safety guard.
    """
    if not confirm:
        return False
    import shutil
    ws_id = validate_workspace_id(ws_id)
    path = _session_path(session_id, ws_id)
    msg_dir = _session_dir(ws_id) / str(session_id)

    deleted = False
    if path.is_file():
        try:
            path.unlink()
            deleted = True
        except Exception:
            pass

    # Also remove the messages directory to prevent auto-repair resurrection
    if msg_dir.is_dir():
        try:
            shutil.rmtree(msg_dir)
            deleted = True
        except Exception:
            pass

    return deleted


# ─── Run association ───


def add_run_to_session(
    session_id: str, run_id: str, ws_id: str = "default"
) -> Optional[Dict[str, Any]]:
    """Append a run_id to a session's run_ids list."""
    ws_id = validate_workspace_id(ws_id)
    session = get_session(session_id, ws_id)
    if not session:
        return None

    run_ids = session.get("run_ids", [])
    if run_id not in run_ids:
        run_ids.append(run_id)
        session["run_ids"] = run_ids
        session["updated_at"] = _now_iso()
        # Auto-title: use first user input as session name
        if not session.get("title"):
            title = _auto_title_from_run(run_id, ws_id)
            if title:
                session["title"] = title
        _write_session(session, ws_id)
    return session


def _auto_title_from_run(run_id: str, ws_id: str) -> str:
    """Generate a human-friendly title from the run's user input."""
    try:
        from workspace.run_store import get_run
        run = get_run(run_id, ws_id)
        if run:
            text = (run.get("user_input_summary") or "").strip()
            if text and len(text) > 3:
                return text[:40] + ("..." if len(text) > 40 else "")
    except Exception:
        pass
    return ""


def get_session_messages(session_id: str, ws_id: str = "default") -> List[Dict[str, Any]]:
    """Return a session's messages for chat UI restoration.

    Full message files are canonical for current runs. Older or interrupted
    runs may have a valid session association but no message files; in that
    case, project the sanitized run summaries into chat messages. Missing or
    deleted sessions never fall back to runs, so deletion semantics remain
    intact.
    """
    from workspace.message_store import SessionMessageStore

    if get_session(session_id, ws_id) is None:
        return []

    store = SessionMessageStore(session_id=session_id, ws_id=ws_id)
    messages = store.get_messages()
    if messages:
        return messages

    from workspace.run_store import list_runs, run_sort_key

    runs = [
        run for run in list_runs(ws_id, limit=100_000)
        if run.get("session_id") == session_id
    ]
    runs.sort(key=run_sort_key)

    projected: List[Dict[str, Any]] = []
    for run in runs:
        run_id = str(run.get("run_id") or run.get("turn_id") or "").strip()
        if not run_id:
            continue
        created_at = (
            run.get("created_at")
            or run.get("started_at")
            or run.get("finished_at")
            or ""
        )
        metadata = {
            key: run[key]
            for key in (
                "intent",
                "status",
                "capability",
                "quality_summary",
                "manual_review_count",
                "trace_id",
                "llm_metadata",
            )
            if key in run
        }
        user_content = str(run.get("user_input_summary") or "").strip()
        assistant_content = str(run.get("final_response_summary") or "").strip()
        if user_content:
            projected.append({
                "message_id": f"{run_id}:user",
                "session_id": session_id,
                "role": "user",
                "content": user_content,
                "created_at": created_at,
                "run_id": run_id,
                "metadata": metadata,
            })
        if assistant_content:
            projected.append({
                "message_id": f"{run_id}:assistant",
                "session_id": session_id,
                "role": "assistant",
                "content": assistant_content,
                "created_at": created_at,
                "run_id": run_id,
                "metadata": metadata,
            })
    return projected


def get_or_create_default_session(ws_id: str = "default") -> Dict[str, Any]:
    """Get the most recent active session, or create one if none exists."""
    sessions = list_sessions(ws_id, status="active", limit=1)
    if sessions:
        return sessions[0]
    return create_session(ws_id, title="默认会话")


def auto_title_from_input(session_id: str, user_input: str, ws_id: str = "default") -> Optional[str]:
    """Auto-generate a session title from the first user input if the title is generic.

    Returns the new title if updated, None otherwise.
    """
    ws_id = validate_workspace_id(ws_id)
    session = get_session(session_id, ws_id)
    if not session:
        return None

    current_title = session.get("title", "")
    # Only auto-title if current title is generic
    if current_title not in ("新会话", "默认会话", ""):
        return None

    # Use first 20 chars of user input as title
    title = user_input.strip()
    if len(title) > 20:
        title = title[:20] + "..."
    if not title:
        return None

    update_session(session_id, ws_id, title=title)
    return title


# ─── Internal helpers ───


def _write_session(session: Dict[str, Any], ws_id: str):
    """Persist session to disk atomically to prevent corruption on concurrent writes."""
    _session_dir(ws_id).mkdir(parents=True, exist_ok=True)
    path = _session_path(session["session_id"], ws_id)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(session, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.rename(path)  # atomic on POSIX


# ─── Cleanup helpers ───


def list_sessions_by_status(ws_id: str = "default") -> Dict[str, List[Dict[str, Any]]]:
    """Return sessions grouped by status."""
    ws_id = ensure_workspace(ws_id)
    all_sessions = []
    sdir = _session_dir(ws_id)
    if sdir.is_dir():
        for f in sdir.glob("*.json"):
            try:
                all_sessions.append(json.loads(f.read_text(encoding="utf-8")))
            except Exception:
                pass

    return {
        "active": [s for s in all_sessions if s.get("status") == "active"],
        "archived": [s for s in all_sessions if s.get("status") == "archived"],
        "deleted": [s for s in all_sessions if s.get("status") == "deleted"],
    }


def get_session_count(ws_id: str = "default") -> Dict[str, int]:
    """Return counts of sessions by status."""
    grouped = list_sessions_by_status(ws_id)
    return {
        "active": len(grouped["active"]),
        "archived": len(grouped["archived"]),
        "deleted": len(grouped["deleted"]),
        "total": len(grouped["active"]) + len(grouped["archived"]) + len(grouped["deleted"]),
    }
