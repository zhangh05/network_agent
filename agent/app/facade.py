# agent/app/facade.py
"""AgentApp — main entry point for the Codex-style runtime."""

import logging
import time
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

    def _evict_expired(self):
        """Remove sessions that exceed TTL or max count."""
        now = time.time()
        # Evict by TTL
        expired = [
            sid for sid, s in self._sessions.items()
            if now - getattr(s, "_last_access", 0) > _SESSION_TTL_SECONDS
        ]
        for sid in expired:
            del self._sessions[sid]

        # Evict oldest if still over max
        if len(self._sessions) > _MAX_SESSIONS:
            sorted_sids = sorted(
                self._sessions.keys(),
                key=lambda sid: getattr(self._sessions[sid], "_last_access", 0),
            )
            overflow = len(self._sessions) - _MAX_SESSIONS
            for sid in sorted_sids[:overflow]:
                del self._sessions[sid]

    def submit_user_message(
        self,
        user_input: str,
        session_id: str = None,
        workspace_id: str = "default",
        metadata: dict = None,
    ) -> "AgentResult":
        """Submit a user message and return AgentResult."""
        self._evict_expired()

        # Create or retrieve session
        sid = session_id or f"session_{len(self._sessions)}"
        if sid not in self._sessions:
            session = AgentSession(session_id=sid, workspace_id=workspace_id, services=self.services)
            self._sessions[sid] = session
            # v2.4: restore session history from disk to avoid blank history
            # after process restart or TTL expiry
            _restore_session_history(session, sid, workspace_id)
        else:
            session = self._sessions[sid]

        # Track last access time for eviction
        session._last_access = time.time()

        # Create op and thread
        op = AgentOp.user_message(user_input=user_input, session_id=sid, workspace_id=workspace_id, metadata=metadata)
        thread = AgentThread(session=session)

        # Submit and return result
        return thread.submit(op)
