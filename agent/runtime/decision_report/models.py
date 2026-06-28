# agent/runtime/decision_report/models.py
"""Decision Report — data models for per-turn audit records."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

REPORT_SCHEMA_VERSION = "decision_report.v2"


@dataclass
class ExecutionSummary:
    """Summary of tool execution outcomes for this turn."""

    called: list = field(default_factory=list)
    blocked: list = field(default_factory=list)
    failed: list = field(default_factory=list)
    succeeded: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "called": list(self.called),
            "blocked": list(self.blocked),
            "failed": list(self.failed),
            "succeeded": list(self.succeeded),
        }


@dataclass
class TraceSummary:
    """Trace statistics — real vs synthetic events."""

    real_event_count: int = 0
    synthetic_event_count: int = 0
    missing_event_count: int = 0

    def to_dict(self) -> dict:
        return {
            "real_event_count": self.real_event_count,
            "synthetic_event_count": self.synthetic_event_count,
            "missing_event_count": self.missing_event_count,
        }


@dataclass
class RetrievalDecision:
    """Memory / knowledge retrieval decisions for this turn.

    Populated by RetrievalTriggerPolicy.
    """

    memory: dict = field(default_factory=lambda: {"status": "not_evaluated"})
    knowledge: dict = field(default_factory=lambda: {"status": "not_evaluated"})

    def to_dict(self) -> dict:
        return {
            "memory": dict(self.memory),
            "knowledge": dict(self.knowledge),
        }


@dataclass
class DecisionReport:
    """Per-turn machine-readable decision report.

    Written to workspaces/<ws>/runs/<run_id>.decision.json.
    Contains everything needed to answer "why did the Agent do this?"
    """

    schema_version: str = REPORT_SCHEMA_VERSION
    run_id: str = ""
    session_id: str = ""
    workspace_id: str = ""
    created_at: str = ""

    # Scene decision from cognition layer
    scene_decision: dict = field(default_factory=dict)

    # Business capability guidance from agent.capabilities.catalog
    business_capabilities: list = field(default_factory=list)

    # Tool planning decision (from P0)
    tool_planning_decision: dict = field(default_factory=dict)

    # Visibility violations detected during execution
    visibility_violations: list = field(default_factory=list)

    # Retrieval decision stubs (P1-B)
    retrieval_decision: dict = field(default_factory=lambda: {
        "memory": {"status": "not_evaluated"},
        "knowledge": {"status": "not_evaluated"},
    })

    context_pipeline: dict = field(default_factory=dict)
    decision_status: str = "degraded"

    # Tool execution summary
    tool_execution_summary: dict = field(default_factory=lambda: {
        "called": [], "blocked": [], "failed": [], "succeeded": [],
    })

    # Trace statistics
    trace_summary: dict = field(default_factory=lambda: {
        "real_event_count": 0,
        "synthetic_event_count": 0,
        "missing_event_count": 0,
    })

    # Turn-level warnings and errors
    warnings: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    # Whether redaction was applied before writing
    redaction_applied: bool = True

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "session_id": self.session_id,
            "workspace_id": self.workspace_id,
            "created_at": self.created_at,
            "scene_decision": dict(self.scene_decision),
            "business_capabilities": list(self.business_capabilities),
            "tool_planning_decision": dict(self.tool_planning_decision),
            "visibility_violations": list(self.visibility_violations),
            "retrieval_decision": dict(self.retrieval_decision),
            "context_pipeline": dict(self.context_pipeline),
            "decision_status": self.decision_status,
            "tool_execution_summary": dict(self.tool_execution_summary),
            "trace_summary": dict(self.trace_summary),
            "warnings": [
                str(w)[:500] for w in (self.warnings or [])
            ],
            "errors": [
                str(e)[:500] for e in (self.errors or [])
            ],
            "redaction_applied": self.redaction_applied,
        }
