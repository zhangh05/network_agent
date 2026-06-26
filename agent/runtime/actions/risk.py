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


def _has_conflicts(evidence_bundle) -> bool:
    """Check if an evidence bundle contains conflicting entries."""
    if isinstance(evidence_bundle, dict):
        return bool(evidence_bundle.get("conflicts"))
    if hasattr(evidence_bundle, "conflicts"):
        return bool(evidence_bundle.conflicts)
    return False


def _apply_conflict_risk(decision: RiskDecision, plan: ActionPlan, evidence_bundle) -> None:
    """Escalate actions when current evidence contains unresolved conflicts."""
    if not _has_conflicts(evidence_bundle):
        return
    if plan.action_class not in ("execute", "mutate", "write"):
        return
    decision.approval_required = True
    if "evidence_conflict_requires_approval" not in decision.warnings:
        decision.warnings.append("evidence_conflict_requires_approval")
    if plan.action_class == "execute" and decision.risk_level not in ("high", "critical"):
        decision.risk_level = "high"


class RiskPolicy:
    """Evaluate risk of an ActionPlan and return a RiskDecision."""

    def evaluate(self, plan: ActionPlan, *, ctx=None,
                 evidence_bundle=None) -> RiskDecision:
        """Assess risk based on action class, tool id, arguments, and evidence.

        If the caller does not pass an evidence bundle explicitly, the policy
        falls back to ``ctx.evidence_bundle``. Unresolved evidence conflicts force
        approval for write/mutate/execute actions and keep execute actions high
        risk at minimum.
        """
        if evidence_bundle is None and ctx is not None:
            evidence_bundle = getattr(ctx, "evidence_bundle", None)

        decision = RiskDecision(
            action_id=plan.action_id,
            action_class=plan.action_class,
        )

        # v3.10 Phase 5: Read risk from Capability Manifest as primary source
        manifest = None
        try:
            from tool_runtime.manifest_registry import get_manifest
            manifest = get_manifest(plan.tool_id)
        except Exception:
            pass

        # If manifest exists, use its declared risk level and approval requirement
        if manifest:
            # Check dangerous args FIRST — they override manifest risk_level
            dangerous_match = _check_dangerous_commands(plan.arguments)
            if dangerous_match:
                decision.risk_level = "critical"
                decision.approval_required = True
                decision.reason = f"Dangerous command pattern detected: {dangerous_match}"
                decision.warnings.append("dangerous_command_requires_approval")
            else:
                decision.risk_level = manifest.risk_level
                decision.approval_required = manifest.requires_approval
                decision.reason = manifest.approval_reason_template or f"{manifest.action_class} action: {manifest.display_name}"
                # Safety floor: manifest can only tighten, not relax. Force approval for mutate/delete.
                if plan.action_class in ("mutate", "delete") and not decision.approval_required:
                    decision.approval_required = True
                    decision.warnings.append("safety_floor_mutate_requires_approval")
            plan.risk_level = decision.risk_level
            _apply_conflict_risk(decision, plan, evidence_bundle)
            return decision

        # 1. Check for dangerous commands in arguments → critical, needs approval
        dangerous_match = _check_dangerous_commands(plan.arguments)
        if dangerous_match:
            decision.risk_level = "critical"
            decision.approval_required = True
            decision.reason = f"Dangerous command pattern detected: {dangerous_match}"
            decision.warnings.append("dangerous_command_requires_approval")
            _apply_conflict_risk(decision, plan, evidence_bundle)
            plan.risk_level = decision.risk_level
            return decision

        # 2. Shell/python/powershell execute → low (no restriction)
        #    Approval only triggers for dangerous patterns caught above.
        if _is_execute_tool(plan.tool_id) or plan.action_class == "execute":
            decision.risk_level = "low"
            decision.reason = "Execute-class tool — risk assessed per-command"
            _apply_conflict_risk(decision, plan, evidence_bundle)
            plan.risk_level = decision.risk_level
            return decision

        # 3. Classify by action_class
        if plan.action_class == "read":
            decision.risk_level = "low"
            decision.reason = "Read-only operation"
            _apply_conflict_risk(decision, plan, evidence_bundle)
            plan.risk_level = decision.risk_level
            return decision

        if plan.action_class == "write":
            decision.risk_level = "medium"
            decision.reason = "Write operation"
            _apply_conflict_risk(decision, plan, evidence_bundle)
            plan.risk_level = decision.risk_level
            return decision

        if plan.action_class == "mutate":
            decision.risk_level = "medium-high"
            decision.approval_required = True
            decision.reason = "Destructive/mutate operation"
            _apply_conflict_risk(decision, plan, evidence_bundle)
            plan.risk_level = decision.risk_level
            return decision

        if plan.action_class == "external":
            decision.risk_level = "medium"
            decision.reason = "External API call"
            _apply_conflict_risk(decision, plan, evidence_bundle)
            plan.risk_level = decision.risk_level
            return decision

        # Default
        decision.risk_level = "low"
        decision.reason = "Default low risk"
        _apply_conflict_risk(decision, plan, evidence_bundle)
        plan.risk_level = decision.risk_level
        return decision
