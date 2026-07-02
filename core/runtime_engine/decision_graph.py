"""
SSOT Runtime v10.1 Decision Graph — purely declarative rule resolution.

No if/else branching.  All routing is driven by a declarative
rule table evaluated by DecisionPolicyResolver.resolve().
"""

from __future__ import annotations

from typing import Any


# ── v10.1: Declarative rule table ─────────────────────────────────────────

DecisionPolicySpec: list[tuple[str, str]] = [
    # (condition, action)
    ("CRITICAL", "STOP"),
    ("HIGH", "DEGRADE"),
    ("retryable AND source=PLANNER", "RETRY_PLANNER"),
    ("retryable AND source=TOOL", "RETRY_TOOL"),
    ("retryable", "RETRY_FULL"),
    ("DEFAULT", "RUN"),
]


class DecisionPolicyResolver:
    """v10.1: pure rule-matching engine — no if/else."""

    @staticmethod
    def resolve(report: Any) -> str:
        """Match rules in order; return the first matched action."""
        for condition, action in DecisionPolicySpec:
            if _match(condition, report):
                return action
        return "RUN"  # unreachable (DEFAULT catches all)

    @staticmethod
    def resolve_with_trace(report: Any) -> tuple[str, str, list[dict[str, str]]]:
        """Resolve with full trace of rule evaluations."""
        trace: list[dict[str, str]] = []
        for condition, action in DecisionPolicySpec:
            matched = _match(condition, report)
            trace.append({"condition": condition, "action": action,
                          "matched": str(matched)})
            if matched:
                return action, condition, trace
        return "RUN", "DEFAULT", trace


def _match(condition: str, report: Any) -> bool:
    """Evaluate a single rule condition against the report."""
    if condition == "DEFAULT":
        return True
    if condition == "CRITICAL":
        return getattr(report, "critical_count", 0) > 0
    if condition == "HIGH":
        return getattr(report, "high_count", 0) > 0
    if condition == "retryable":
        return bool(getattr(report, "recoverable", False))

    # Compound conditions
    if " AND " in condition:
        parts = condition.split(" AND ")
        return all(_match(p.strip(), report) for p in parts)

    # Named conditions
    if condition.startswith("source="):
        expected = condition.split("=", 1)[1]
        actual = str(getattr(report, "source", "")).upper()
        return expected.upper() in actual

    return False


class DecisionNode:
    def __init__(self, name: str, action: str, reason: str):
        self.name = name
        self.action = action
        self.reason = reason


class DecisionGraph:
    """v10.1: single decision entry with declarative resolver."""

    def __init__(self):
        self.nodes: list[DecisionNode] = []

    def decide(self, ctx: Any, failure_report: Any) -> DecisionNode:
        action, cond, _ = DecisionPolicyResolver.resolve_with_trace(failure_report)
        node = DecisionNode("decision_graph", action,
                            f"rule: {cond} (CRITICAL={getattr(failure_report, 'critical_count', 0)}, HIGH={getattr(failure_report, 'high_count', 0)})")
        self.nodes.append(node)
        return node

    def to_trace(self) -> list[dict[str, str]]:
        return [{"name": n.name, "action": n.action, "reason": n.reason}
                for n in self.nodes]


__all__ = ["DecisionGraph", "DecisionNode", "DecisionPolicySpec",
           "DecisionPolicyResolver"]

