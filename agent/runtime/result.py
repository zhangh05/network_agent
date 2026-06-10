# agent/runtime/result.py
"""AgentResult — final output of a turn execution."""

from dataclasses import dataclass, field


@dataclass
class AgentResult:
    ok: bool = False
    final_response: str = ""
    events: list = field(default_factory=list)
    trace_id: str = ""
    session_id: str = ""
    turn_id: str = ""
    tool_calls: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "final_response": self.final_response,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "trace_id": self.trace_id,
            "tool_calls": self.tool_calls,
            "warnings": self.warnings,
            "errors": self.errors,
            "metadata": self.metadata,
        }
