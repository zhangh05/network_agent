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
    """
    ws_id = ensure_workspace(ws_id)
    sdir = _session_dir(ws_id)
    if not sdir.is_dir():
        return []

    sessions = []
    for f in sdir.glob("*.json"):
        try:
            s = json.loads(f.read_text(encoding="utf-8"))
            sessions.append(s)
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
    """Physically delete the session metadata file. Run records are NOT deleted.

    Requires confirm=True as a safety guard.
    """
    if not confirm:
        return False
    ws_id = validate_workspace_id(ws_id)
    path = _session_path(session_id, ws_id)
    if path.is_file():
        try:
            path.unlink()
            return True
        except Exception:
            pass
    return False


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
        _write_session(session, ws_id)
    return session


def get_session_messages(session_id: str, ws_id: str = "default") -> List[Dict[str, Any]]:
    """Convert a session's runs into a message list for chat UI restoration.

    v1.0.3.1: delegates to workspace.message_store.SessionMessageStore
    so the message_id (and every other field) is identical across
    every read. The implementation is the single source of truth;
    this function remains as a thin re-export.

    Each run produces two messages:
      - role: 'user', message_id: '<run_id>:user', content: user_input_summary
      - role: 'assistant', message_id: '<run_id>:assistant',
              content: final_response_summary + metadata

    Messages are ordered by run creation time.
    """
    from workspace.message_store import SessionMessageStore
    store = SessionMessageStore(session_id=session_id, ws_id=ws_id)
    return store.get_messages()


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
