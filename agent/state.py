# agent/state.py
"""NetworkAgentState — shared state across all LangGraph nodes."""

import uuid
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class NetworkAgentState:
    """Canonical state for Network Agent LangGraph workflow."""

    request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    user_input: str = ""
    intent: Optional[str] = None
    active_module: Optional[str] = None
    workspace_id: str = "default"
    session_id: Optional[str] = None

    selected_skill: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    context: Dict[str, Any] = field(default_factory=dict)
    memory_hits: List[Dict[str, Any]] = field(default_factory=list)

    plan: List[str] = field(default_factory=list)

    # ── Skill / Capability execution records ──
    # skill_calls / skill_results are the PRIMARY fields for skill/capability
    # execution records. They hold skill adapter invocation metadata and results.
    skill_calls: List[Dict[str, Any]] = field(default_factory=list)
    skill_results: Dict[str, Any] = field(default_factory=dict)

    # DEPRECATED: tool_calls / tool_results are pre-ToolRuntime naming.
    # They alias skill_calls / skill_results for backward compatibility with
    # old state, trace, run, and test code. Do NOT use these for new Tool Runtime.
    # Future Tool Runtime will use independent ToolSpec / ToolInvocation / ToolResult.
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    tool_results: Dict[str, Any] = field(default_factory=dict)

    verification: Dict[str, Any] = field(default_factory=dict)
    final_response: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    error: Optional[str] = None

    # ── UI Actions — Agent → Frontend instruction bridge ──
    # Each entry: {action: str, target: str, value: Optional[str], params: dict}
    ui_actions: List[Dict[str, Any]] = field(default_factory=list)

    runtime_mode: str = "fallback"  # langgraph | fallback
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = ""

    # ── Observability ──
    trace_id: str = ""
    trace_events: List[Dict[str, Any]] = field(default_factory=list)
    node_timings: Dict[str, float] = field(default_factory=dict)

    def summary(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "intent": self.intent,
            "active_module": self.active_module,
            "selected_skill": self.selected_skill,
            "runtime_mode": self.runtime_mode,
            "verification": self.verification,
            "warnings": self.warnings,
        }
