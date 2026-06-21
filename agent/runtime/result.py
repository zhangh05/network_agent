# agent/runtime/result.py
"""AgentResult — final output of a turn execution.

v2.1.2: Added tool_decision field for tool-use transparency.
"""

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
    error_type: str = ""
    # v2.1.2: Tool decision transparency
    tool_decision: dict = field(default_factory=dict)
    no_tool_reason: str = ""

    # v3.3.4: transient finalization context (NOT serialized in to_dict)
    _finalization_ctx: object = None

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "final_response": self.final_response,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "trace_id": self.trace_id,
            "events": self.events,
            "tool_calls": self.tool_calls,
            "warnings": self.warnings,
            "errors": self.errors,
            "metadata": self.metadata,
            "error_type": self.error_type,
            "tool_decision": self.tool_decision,
            "no_tool_reason": self.no_tool_reason,
            "timeline_summary": self.metadata.get("timeline_summary", {}),
        }
