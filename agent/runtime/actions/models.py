# agent/runtime/actions/models.py
"""Action execution kernel data models."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional


def _new_action_id() -> str:
    return f"act_{uuid.uuid4().hex[:12]}"


@dataclass
class ActionRequest:
    """Raw incoming tool call before planning."""
    action_id: str = field(default_factory=_new_action_id)
    turn_id: str = ""
    tool_call_id: str = ""
    tool_name: str = ""
    tool_id: str = ""
    arguments: dict = field(default_factory=dict)
    raw_call: Any = None
    source: str = "llm"


@dataclass
class ActionPlan:
    """Planned action with classification and risk assessment."""
    action_id: str = field(default_factory=_new_action_id)
    turn_id: str = ""
    tool_call_id: str = ""
    tool_name: str = ""
    tool_id: str = ""
    arguments: dict = field(default_factory=dict)
    action_class: str = "unknown"       # read/write/mutate/execute/external
    risk_level: str = "low"             # low/medium/high/critical
    approval_required: bool = False
    approval_reason: str = ""
    evidence_refs: list = field(default_factory=list)
    context_refs: list = field(default_factory=list)
    argument_sources: dict = field(default_factory=dict)
    status: str = "planned"             # planned/approved/rejected/executing/success/failed
    warnings: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class RiskDecision:
    """Output of risk policy evaluation."""
    action_id: str = ""
    risk_level: str = "low"
    action_class: str = "unknown"
    approval_required: bool = False
    blocked: bool = False
    reason: str = ""
    warnings: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class ApprovalDecision:
    """Output of approval gate."""
    action_id: str = ""
    required: bool = False
    approved: bool = False
    status: str = "not_required"        # not_required/pending/approved/rejected
    reason: str = ""
    prompt: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class ActionResult:
    """Full result of an action execution."""
    action_id: str = ""
    tool_call_id: str = ""
    tool_name: str = ""
    tool_id: str = ""
    ok: bool = False
    status: str = "failed"              # success/failed/blocked/approval_pending/timeout
    result: Any = None
    normalized_result: Any = None
    error: str = ""
    error_type: str = ""
    retryable: bool = False
    attempts: int = 0
    scan_status: str = "skipped"        # safe/summary/blocked/skipped
    evidence_updates: list = field(default_factory=list)
    artifact_refs: list = field(default_factory=list)
    # v3.9.8: started_at / finished_at / latency_ms are now ISO-8601
    # strings / int milliseconds to match RuntimeStep, TrajectoryRecord,
    # and ToolResult. Float-epoch caused API-boundary type drift.
    started_at: str = ""
    finished_at: str = ""
    latency_ms: int = 0
    metadata: dict = field(default_factory=dict)
