# agent/app/facade.py
"""AgentApp — main entry point for the Codex-style runtime."""

import logging
import threading
import time
import uuid
from agent.core.session import AgentSession
from agent.core.thread import AgentThread
from agent.protocol.op import AgentOp

# Session TTL: idle sessions older than this are evicted on next access
_SESSION_TTL_SECONDS = 3600  # 1 hour
# Max sessions before forced eviction of oldest
_MAX_SESSIONS = 1000

logger = logging.getLogger(__name__)


def _restore_session_history(session, session_id: str, workspace_id: str):
    """Restore session.history from disk (SessionMessageStore).

    Bridges the gap between in-memory session eviction (process restart,
    TTL expiry) and disk-persisted messages. Without this, a recreated
    session starts with an empty history, causing the "conversation
    history not showing" bug.
    """
    try:
        from workspace.message_store import SessionMessageStore
        from agent.protocol.message import UserMessage, AssistantMessage
        store = SessionMessageStore(session_id=session_id, ws_id=workspace_id or "default")
        msgs = store.get_messages()
        if msgs:
            history = []
            for m in msgs:
                role = m.get("role", "")
                content = m.get("content", "")
                if role == "user" and content:
                    history.append(UserMessage(content=content))
                elif role == "assistant" and content:
                    history.append(AssistantMessage(content=content))
            if history:
                session.history = history
                logger.info("Restored %d history messages for session %s from disk", len(history), session_id)
    except Exception as e:
        logger.warning("Failed to restore session history from disk for %s: %s", session_id, e)


class AgentApp:
    def __init__(self, services=None):
        if services is None:
            from agent.runtime.services import default_runtime_services
            services = default_runtime_services()
        self.services = services
        self._sessions: dict = {}
        # Protects the session map, session creation, TTL eviction, and
        # per-session lock map. The turn itself is executed outside this
        # lock, guarded by the individual session lock below.
        self._sessions_lock = threading.RLock()
        self._session_turn_locks: dict[str, threading.RLock] = {}

    def _new_session_id(self) -> str:
        return f"session_{uuid.uuid4().hex[:12]}"

    def _evict_expired_locked(self):
        """Remove sessions that exceed TTL or max count.

        Caller must hold self._sessions_lock.
        """
        now = time.time()
        # Evict by TTL
        expired = [
            sid for sid, s in self._sessions.items()
            if now - getattr(s, "_last_access", 0) > _SESSION_TTL_SECONDS
        ]
        for sid in expired:
            del self._sessions[sid]
            self._session_turn_locks.pop(sid, None)

        # Evict oldest if still over max
        if len(self._sessions) > _MAX_SESSIONS:
            sorted_sids = sorted(
                self._sessions.keys(),
                key=lambda sid: getattr(self._sessions[sid], "_last_access", 0),
            )
            overflow = len(self._sessions) - _MAX_SESSIONS
            for sid in sorted_sids[:overflow]:
                del self._sessions[sid]
                self._session_turn_locks.pop(sid, None)

    def _get_or_create_session_locked(self, sid: str, workspace_id: str):
        """Return (session, turn_lock), creating both atomically.

        Caller must hold self._sessions_lock.
        """
        if sid not in self._sessions:
            session = AgentSession(session_id=sid, workspace_id=workspace_id, services=self.services)
            self._sessions[sid] = session
            self._session_turn_locks[sid] = threading.RLock()
            # v2.4: restore session history from disk to avoid blank history
            # after process restart or TTL expiry. This runs before the
            # session is released to a turn, so no request can observe a
            # half-restored history window.
            _restore_session_history(session, sid, workspace_id)
        else:
            session = self._sessions[sid]
            self._session_turn_locks.setdefault(sid, threading.RLock())

        session._last_access = time.time()
        return session, self._session_turn_locks[sid]

    def submit_user_message(
        self,
        user_input: str,
        session_id: str = None,
        workspace_id: str = "default",
        metadata: dict = None,
    ) -> "AgentResult":
        """Submit a user message and return AgentResult.

        Runtime hardening:
        - session map access is serialized to avoid concurrent creation races;
        - implicit sessions use UUIDs instead of len(self._sessions);
        - turns for the same session are serialized to prevent history,
          context, tool-result, and trace cross-talk.
        """
        with self._sessions_lock:
            self._evict_expired_locked()
            sid = session_id or self._new_session_id()
            session, turn_lock = self._get_or_create_session_locked(sid, workspace_id)

        # The expensive turn execution happens outside the global session-map
        # lock, but inside this session's turn lock. Different sessions can run
        # concurrently; the same session cannot interleave turns.
        with turn_lock:
            if metadata is None:
                metadata = {}
            elif not isinstance(metadata, dict):
                metadata = {}
            metadata = dict(metadata)
            metadata.setdefault("turn_serialization", "per_session")

            op = AgentOp.user_message(user_input=user_input, session_id=sid, workspace_id=workspace_id, metadata=metadata)
            thread = AgentThread(session=session)
            return thread.submit(op)
