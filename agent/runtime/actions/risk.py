# agent/runtime/actions/risk.py
"""RiskPolicy — evaluates ActionPlan risk level."""

from __future__ import annotations

import re
from typing import Optional

from agent.runtime.actions.models import ActionPlan, RiskDecision


# ── Dangerous command patterns → critical / blocked ──────────────────────

_DANGEROUS_PATTERNS = [
    re.compile(r"rm\s+-(r|f|rf|fr)\s", re.I),
    re.compile(r"rm\s+-f\s+/", re.I),
    re.compile(r"del\s+/s\b", re.I),
    re.compile(r"\bformat\s+[A-Za-z]:", re.I),
    re.compile(r"\bmkfs\b", re.I),
    re.compile(r"\bshutdown\b", re.I),
    re.compile(r"\breboot\b", re.I),
    re.compile(r"\bchmod\s+777\b", re.I),
    re.compile(r"curl\s.*\|\s*sh", re.I),
    re.compile(r"wget\s.*\|\s*sh", re.I),
    re.compile(r"curl\s.*\|\s*bash", re.I),
    re.compile(r"wget\s.*\|\s*bash", re.I),
    re.compile(r"Invoke-Expression\b", re.I),
    re.compile(r"\biex\b", re.I),
    re.compile(r"Remove-Item\s.*-Recurse\s.*-Force", re.I),
    re.compile(r"Remove-Item\s.*-Force\s.*-Recurse", re.I),
]

# ── Execute tools (shell/python/powershell) → high ───────────────────────

_EXECUTE_TOOL_PATTERNS = re.compile(
    r"(shell|powershell|python)\b.*\b(exec|run|execute)\b"
    r"|\b(exec|run|execute)\b.*\b(shell|powershell|python)\b"
    r"|host\.(shell|powershell|python)\.exec",
    re.I,
)


def _check_dangerous_commands(arguments: dict) -> Optional[str]:
    """Check if any argument value contains a dangerous command pattern."""
    for val in arguments.values():
        if not isinstance(val, str):
            continue
        for pat in _DANGEROUS_PATTERNS:
            if pat.search(val):
                return pat.pattern
    return None


def _is_execute_tool(tool_id: str) -> bool:
    """Check if tool_id represents a shell/python/powershell execution."""
    return bool(_EXECUTE_TOOL_PATTERNS.search(tool_id))


class RiskPolicy:
    """Evaluate risk of an ActionPlan and return a RiskDecision."""

    def evaluate(self, plan: ActionPlan, *, ctx=None,
                 evidence_bundle=None) -> RiskDecision:
        """Assess risk based on action class, tool id, and arguments.

        When *evidence_bundle* has conflicts and the action is execute/mutate,
        approval_required is forced True.  plan.risk_level is updated in-place.
        """
        decision = RiskDecision(
            action_id=plan.action_id,
            action_class=plan.action_class,
        )

        # 1. Check for dangerous commands in arguments → critical, blocked
        dangerous_match = _check_dangerous_commands(plan.arguments)
        if dangerous_match:
            decision.risk_level = "critical"
            decision.blocked = True
            decision.approval_required = True
            decision.reason = f"Dangerous command pattern detected: {dangerous_match}"
            decision.warnings.append("critical_command_blocked")
            plan.risk_level = decision.risk_level
            return decision

        # 2. Shell/python/powershell execute → high
        if _is_execute_tool(plan.tool_id) or plan.action_class == "execute":
            decision.risk_level = "high"
            decision.approval_required = True
            decision.reason = "Execute-class tool requires approval"
            plan.risk_level = decision.risk_level
            # Evidence-bundle conflict escalation
            if evidence_bundle and _has_conflicts(evidence_bundle) and plan.action_class in ("execute", "mutate"):
                decision.approval_required = True
            return decision

        # 3. Classify by action_class
        if plan.action_class == "read":
            decision.risk_level = "low"
            decision.reason = "Read-only operation"
            plan.risk_level = decision.risk_level
            return decision

        if plan.action_class == "write":
            decision.risk_level = "medium"
            decision.reason = "Write operation"
            plan.risk_level = decision.risk_level
            return decision

        if plan.action_class == "mutate":
            decision.risk_level = "medium-high"
            decision.approval_required = True
            decision.reason = "Destructive/mutate operation"
            # Evidence-bundle conflict escalation
            if evidence_bundle and _has_conflicts(evidence_bundle):
                decision.approval_required = True
            plan.risk_level = decision.risk_level
            return decision

        if plan.action_class == "external":
            decision.risk_level = "medium"
            decision.reason = "External API call"
            plan.risk_level = decision.risk_level
            return decision

        # Default
        decision.risk_level = "low"
        decision.reason = "Default low risk"
        # Evidence-bundle conflict escalation for execute/mutate
        if evidence_bundle and _has_conflicts(evidence_bundle) and plan.action_class in ("execute", "mutate"):
            decision.approval_required = True
        plan.risk_level = decision.risk_level
        return decision


def _has_conflicts(evidence_bundle) -> bool:
    """Check if an evidence bundle contains conflicting entries."""
    if isinstance(evidence_bundle, dict):
        return bool(evidence_bundle.get("conflicts"))
    if hasattr(evidence_bundle, "conflicts"):
        return bool(evidence_bundle.conflicts)
    return False
