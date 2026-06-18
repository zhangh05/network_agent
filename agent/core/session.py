# agent/core/session.py
"""AgentSession — long-lived conversation state."""

import uuid
from dataclasses import dataclass, field


@dataclass
class AgentSession:
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    workspace_id: str = "default"
    history: list = field(default_factory=list)
    services: object = None
    active_turn: object = None
    metadata: dict = field(default_factory=dict)

    def submit(self, op) -> "AgentResult":
        from agent.core.turn import AgentTurn
        from agent.runtime.loop import run_turn
        turn = AgentTurn.from_op(op)
        self.active_turn = turn
        return run_turn(self, turn, self.services)
