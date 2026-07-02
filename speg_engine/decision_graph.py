"""
SPEG v10 Decision Graph — single decision entry point.

All retry / failure / routing decisions flow through exactly one
graph.  No scattered logic, no direct FailurePolicy calls.
"""

from __future__ import annotations

from typing import Any


class DecisionNode:
    """A single decision in the graph."""
    def __init__(self, name: str, action: str, reason: str):
        self.name = name
        self.action = action    # STOP | DEGRADE | RETRY_PLANNER | RETRY_TOOL | RETRY_FULL | RUN
        self.reason = reason


class DecisionGraph:
    """v10: single decision entry — all routing flows through here."""

    def __init__(self):
        self.nodes: list[DecisionNode] = []

    def decide(self, ctx: Any, failure_report: Any) -> DecisionNode:
        """Route the failure report to a single action."""
        node = self._route(failure_report)
        self.nodes.append(node)
        return node

    def _route(self, report: Any) -> DecisionNode:
        if self._is_critical(report):
            return DecisionNode("critical_gate", "STOP",
                                f"CRITICAL={getattr(report, 'critical_count', 0)}")

        if self._is_high(report):
            return DecisionNode("high_gate", "DEGRADE",
                                f"HIGH={getattr(report, 'high_count', 0)}")

        if self._is_retryable(report):
            scope = self._retry_scope(report)
            return DecisionNode("retry_gate", scope, "retryable")

        return DecisionNode("run_gate", "RUN", "clean")

    @staticmethod
    def _is_critical(report: Any) -> bool:
        return getattr(report, "critical_count", 0) > 0

    @staticmethod
    def _is_high(report: Any) -> bool:
        return getattr(report, "high_count", 0) > 0

    @staticmethod
    def _is_retryable(report: Any) -> bool:
        return getattr(report, "recoverable", False)

    @staticmethod
    def _retry_scope(report: Any) -> str:
        src = getattr(report, "source", "")
        if src and "PLANNER" in str(src).upper():
            return "RETRY_PLANNER"
        if src and "TOOL" in str(src).upper():
            return "RETRY_TOOL"
        return "RETRY_FULL"

    def to_trace(self) -> list[dict[str, str]]:
        return [{"name": n.name, "action": n.action, "reason": n.reason}
                for n in self.nodes]


__all__ = ["DecisionGraph", "DecisionNode"]
