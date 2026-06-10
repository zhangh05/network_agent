# agent/app/facade.py
"""AgentApp — main entry point for the v0.6 Codex-style runtime."""

from agent.core.session import AgentSession
from agent.core.thread import AgentThread
from agent.protocol.op import AgentOp


class AgentApp:
    def __init__(self, services=None):
        if services is None:
            from agent.runtime.services import default_runtime_services
            services = default_runtime_services()
        self.services = services
        self._sessions: dict = {}

    def submit_user_message(
        self,
        user_input: str,
        session_id: str = None,
        workspace_id: str = "default",
        metadata: dict = None,
    ) -> "AgentResult":
        """Submit a user message and return AgentResult."""
        # Create or retrieve session
        sid = session_id or f"session_{len(self._sessions)}"
        if sid not in self._sessions:
            session = AgentSession(session_id=sid, workspace_id=workspace_id, services=self.services)
            self._sessions[sid] = session
        else:
            session = self._sessions[sid]

        # Create op and thread
        op = AgentOp.user_message(user_input=user_input, session_id=sid, workspace_id=workspace_id, metadata=metadata)
        thread = AgentThread(session=session)

        # Submit and return result
        return thread.submit(op)
