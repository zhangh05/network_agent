# agent/runtime/decision_report/__init__.py
"""Decision Report — per-turn machine-readable audit record.

Every turn produces a single DecisionReport written to
workspaces/<ws>/runs/<run_id>.decision.json.

It consolidates: scene decision, capability routing, tool planning,
visibility violations, retrieval decisions, execution summary,
and trace statistics — into one authoritative audit document.
"""

from agent.runtime.decision_report.models import (
    DecisionReport,
    ExecutionSummary,
    TraceSummary,
    RetrievalDecision,
    REPORT_SCHEMA_VERSION,
)
from agent.runtime.decision_report.builder import build_decision_report
from agent.runtime.decision_report.writer import write_decision_report
from agent.runtime.decision_report.redaction import redact_decision_report

__all__ = [
    "DecisionReport",
    "ExecutionSummary",
    "TraceSummary",
    "RetrievalDecision",
    "REPORT_SCHEMA_VERSION",
    "build_decision_report",
    "write_decision_report",
    "redact_decision_report",
]
