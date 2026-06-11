"""SessionMessageStore — canonical chat-message persistence for a session.

v1.0.4 introduction.

The runtime previously kept an in-memory `AgentSession.history` list and
ad-hoc built messages from `run_ids → run_records` on demand. Two
divergences came out of this:

  1. In-memory history drifted from disk (turns lost on restart,
     or user reloaded the page).
  2. Each turn produced 2 messages (user + assistant) on read, but
     the same data was also appended to `session.history`, so cross-tab
     or cross-device fetch saw inconsistent state.

`SessionMessageStore` is the single source of truth: it owns the
user_input / final_response projection of a run record and serves
the chat history window the LLM needs. The AgentSession in-memory
list is now a *derived* cache, not the source.

Persistence model:
  - Each `run_id` in `session.run_ids` produces 2 messages.
  - The user's text lives in `run.user_input_summary`.
  - The assistant's text lives in `run.final_response_summary`.
  - The `message_id` is `<run_id>:<role>` (stable across reads).
  - A session's history is the chronological projection of its run_ids.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from workspace.ids import validate_workspace_id, validate_session_id
from workspace.manager import ensure_workspace
from workspace.run_store import get_run


ROOT = Path(__file__).resolve().parent.parent
WS_ROOT = ROOT / "workspaces"


# Stable message_id shape. Pinned so the frontend dedup contract is
# invariant across reads.
USER_MSG_ID = "{run_id}:user"
ASSISTANT_MSG_ID = "{run_id}:assistant"


def _safe_run_id(run_id: str) -> str:
    """Return a run_id with only path-safe chars; raises if empty."""
    safe = re.sub(r'[^a-zA-Z0-9_-]', '', str(run_id))
    if safe != str(run_id) or not safe:
        raise ValueError(f"Invalid run_id: {run_id!r}")
    return safe


class SessionMessageStore:
    """Canonical chat-history read API for a single session.

    Stateless; constructed per-call. The constructor validates
    `ws_id` and `session_id` to prevent path traversal.
    """

    def __init__(self, session_id: str, ws_id: str = "default"):
        self.ws_id = validate_workspace_id(ws_id)
        self.session_id = validate_session_id(session_id)
        # Ensure the workspace exists (idempotent).
        ensure_workspace(self.ws_id)

    # ── Read ──

    def exists(self) -> bool:
        """True if the session record exists on disk."""
        path = self._session_path()
        return path.is_file()

    def get_messages(self) -> List[Dict[str, Any]]:
        """Return the full chat-history projection of the session.

        Each run produces 2 messages (role=user, role=assistant).
        Messages are ordered chronologically by `created_at`.
        The shape matches `SessionMessage` on the frontend.
        """
        from workspace.session_store import get_session
        session = get_session(self.session_id, self.ws_id)
        if not session:
            return []
        return _project_runs_to_messages(session.get("run_ids", []), self.ws_id)

    def get_history_window(self, k: int = 8) -> List[Dict[str, Any]]:
        """Return up to k most recent messages (the LLM context window).

        Messages are returned in chronological order (oldest first),
        so callers can append a new user input and feed to the LLM.
        """
        all_msgs = self.get_messages()
        if k <= 0 or len(all_msgs) <= k:
            return all_msgs
        return all_msgs[-k:]

    def get_message_count(self) -> int:
        return len(self.get_messages())

    # ── Internal ──

    def _session_path(self) -> Path:
        safe = _safe_run_id(self.session_id)
        return WS_ROOT / self.ws_id / "sessions" / f"{safe}.json"


# ── Module-level helpers (used by both runtime and frontend API) ──


def project_runs_to_messages(run_ids: List[str], ws_id: str = "default") -> List[Dict[str, Any]]:
    """Project a list of run_ids into 2 messages per run (user + assistant).

    Module-level so `workspace.session_store.get_session_messages` can
    delegate to it. Stable message_id (`msg_<run_id>_<role>`) is the
    frontend's dedup key.
    """
    return _project_runs_to_messages(run_ids, ws_id)


def _project_runs_to_messages(run_ids: List[str], ws_id: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for run_id in run_ids:
        if not run_id:
            continue
        run = get_run(run_id, ws_id)
        if not run:
            continue

        created = run.get("created_at", "")
        user_text = run.get("user_input_summary", "") or ""
        assistant_text = run.get("final_response_summary", "") or ""
        intent = run.get("intent", "") or ""
        status = run.get("status", "") or ""
        rid = run.get("run_id", "") or run_id
        run_meta = {
            "run_id": rid,
            "intent": intent,
            "status": status,
            "capability": run.get("capability", "") or "",
            "quality_summary": run.get("quality_summary", {}) or {},
            "manual_review_count": run.get("manual_review_count", 0) or 0,
            "trace_id": run.get("trace_id", "") or "",
            "llm_metadata": run.get("llm_metadata", {}) or {},
        }

        # v1.0.4: stable message_id, deterministic from run_id + role.
        if user_text:
            out.append({
                "message_id": USER_MSG_ID.format(run_id=rid),
                "session_id": run.get("session_id", "") or "",
                "role": "user",
                "content": user_text,
                "created_at": created,
                "run_id": rid,
            })
        if assistant_text or intent:
            out.append({
                "message_id": ASSISTANT_MSG_ID.format(run_id=rid),
                "session_id": run.get("session_id", "") or "",
                "role": "assistant",
                "content": assistant_text or "处理完成",
                "created_at": created,
                "run_id": rid,
                "metadata": run_meta,
            })

    out.sort(key=lambda m: m.get("created_at", "") or "")
    return out
