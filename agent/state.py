# agent/state.py
"""NetworkAgentState — shared state across LangGraph nodes."""

from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field


@dataclass
class NetworkAgentState:
    """Canonical state object for the Network Agent orchestrator."""

    user_input: str = ""
    intent: str = ""

    # Module / skill resolution
    active_module: str = ""
    selected_skill: str = ""
    workspace_id: Optional[str] = None

    # Plan
    plan: List[str] = field(default_factory=list)

    # Tool calls
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    tool_results: List[Dict[str, Any]] = field(default_factory=list)

    # Memory
    memory_hits: List[Dict[str, Any]] = field(default_factory=list)

    # Verification
    verification: Dict[str, Any] = field(default_factory=dict)

    # Output
    final_response: str = ""
    error: Optional[str] = None
    done: bool = False
