# agent/core/session.py
"""AgentSession — long-lived conversation state."""

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.runtime.result import AgentResult


@dataclass
class AgentSession:
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    workspace_id: str = ""
    history: list = field(default_factory=list)
    services: object = None
    active_turn: object = None
    metadata: dict = field(default_factory=dict)

    # Trusted runtime marker kept separate from LLM-writable metadata.
    # Internal callers set it through mark_sub_agent().
    _is_sub_agent: bool = False

    def mark_sub_agent(self) -> None:
        """Mark this session as a sub-agent session. Only `run_sub_agent`
        and similar trusted internal callers should invoke this."""
        self._is_sub_agent = True

    @property
    def is_sub_agent(self) -> bool:
        """Read-only access for runtime / context-builder detection."""
        return bool(self._is_sub_agent)

    def submit(self, op) -> "AgentResult":
        from agent.core.turn import AgentTurn
        from agent.runtime.speg_adapter import run_speg_turn
        turn = AgentTurn.from_op(op)
        self.active_turn = turn
        return run_speg_turn(self, turn, self.services)
