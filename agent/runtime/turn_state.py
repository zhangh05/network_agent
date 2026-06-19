# agent/runtime/turn_state.py
"""TurnRuntimeState — dataclass holding all turn-scoped state."""

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class TurnRuntimeState:
    """All mutable state scoped to a single turn execution."""

    # Core references
    session: Any = None
    turn: Any = None
    services: Any = None
    restricted_tool_router: Any = None

    # Built during context / message stages
    context: Any = None
    messages: list = field(default_factory=list)
    tools: list = field(default_factory=list)

    # Agentic loop counters
    step: int = 0
    max_steps: int = 8

    # Accumulated results
    all_tool_results: list = field(default_factory=list)
    final_response: str = ""
    terminal_reason: str = ""
    no_tool_reason: str = ""
    tool_decision: dict = field(default_factory=dict)

    # Metadata / streaming
    metadata: dict = field(default_factory=dict)
    stream_events: list = field(default_factory=list)

    # Runtime infrastructure
    emitter: Any = None
    audit_events: Any = None
    audit_trace: Any = None
