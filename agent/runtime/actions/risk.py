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

    def evaluate(self, plan: ActionPlan) -> RiskDecision:
        """Assess risk based on action class, tool id, and arguments."""
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
            return decision

        # 2. Shell/python/powershell execute → high
        if _is_execute_tool(plan.tool_id) or plan.action_class == "execute":
            decision.risk_level = "high"
            decision.approval_required = True
            decision.reason = "Execute-class tool requires approval"
            return decision

        # 3. Classify by action_class
        if plan.action_class == "read":
            decision.risk_level = "low"
            decision.reason = "Read-only operation"
            return decision

        if plan.action_class == "write":
            decision.risk_level = "medium"
            decision.reason = "Write operation"
            return decision

        if plan.action_class == "mutate":
            decision.risk_level = "medium-high"
            decision.approval_required = True
            decision.reason = "Destructive/mutate operation"
            return decision

        if plan.action_class == "external":
            decision.risk_level = "medium"
            decision.reason = "External API call"
            return decision

        # Default
        decision.risk_level = "low"
        decision.reason = "Default low risk"
        return decision
