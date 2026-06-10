# agent/protocol/op.py
"""AgentOp — submitted by user or system to AgentApp."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class AgentOp:
    op_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    type: str = "user_message"  # user_message | cancel_turn | system_event
    session_id: Optional[str] = None
    workspace_id: str = "default"
    user_input: str = ""
    payload: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @classmethod
    def user_message(cls, user_input: str, session_id: str = None, workspace_id: str = "default", metadata: dict = None) -> "AgentOp":
        return cls(
            type="user_message",
            session_id=session_id or str(uuid.uuid4()),
            workspace_id=workspace_id,
            user_input=user_input,
            metadata=metadata or {},
        )
