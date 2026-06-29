# agent/runtime/actions/risk.py
"""RiskPolicy — evaluates ActionPlan risk level."""

from __future__ import annotations

import re
from typing import Optional

from agent.runtime.actions.models import ActionPlan, RiskDecision
from tool_runtime.dangerous_patterns import scan_arguments_for_dangerous


# ── Dangerous command detection ─────────────────────────────────────────
# v3.9.5: the destructive-pattern list moved to
# tool_runtime/dangerous_patterns (single source of truth). The local
# copy here is gone; the helper is re-exported as
# ``_check_dangerous_commands`` for any caller that still uses it.
_check_dangerous_commands = scan_arguments_for_dangerous


# ── Execute tools (shell/python/powershell) → high ───────────────────────

_EXECUTE_TOOL_PATTERNS = re.compile(
    r"(shell|powershell|python)\b.*\b(exec|run|execute)\b"
    r"|\b(exec|run|execute)\b.*\b(shell|powershell|python)\b"
    r"|host\.(shell|powershell|python)\.exec",
    re.I,
)


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


_READ_ACTIONS = {
    "list", "get", "search", "read", "source_list", "chunk_list",
    "status", "log", "diff", "export", "diagnostics", "health",
    "selfcheck", "tasks", "audit_log", "session_get", "run_get",
    "role_list", "result_get", "find", "load", "inspect",
    "weather", "page", "parse", "summarize", "validate",
}
_DESTRUCTIVE_ACTIONS = {
    "delete", "remove", "purge", "destroy", "drop",
    "delete_file", "session_rewind", "rewind",
}


def _action_name(plan: ActionPlan) -> str:
    return str((plan.arguments or {}).get("action", "")).strip().lower()


def _is_destructive_action(plan: ActionPlan) -> bool:
    action = _action_name(plan)
    return action in _DESTRUCTIVE_ACTIONS or plan.action_class == "delete"


def _base_risk_for_plan(plan: ActionPlan, manifest) -> tuple[str, bool, str]:
    """Return (risk_level, approval_required, reason) for non-dangerous args."""
    action = _action_name(plan)
    display = getattr(manifest, "display_name", plan.tool_id) if manifest else plan.tool_id

    if _is_destructive_action(plan):
        return "high", True, f"Destructive action requires approval: {action or plan.tool_id}"

    if action in _READ_ACTIONS or plan.action_class == "read":
        return "low", False, "Read-only operation"

    if plan.action_class == "execute" or _is_execute_tool(plan.tool_id):
        return "medium", False, "Execute-class tool — risk assessed per-command"

    if plan.action_class in ("write", "mutate", "external"):
        return "medium", False, f"{plan.action_class} action: {display}"

    risk = getattr(manifest, "risk_level", "") if manifest else ""
    if risk in ("low", "medium"):
        return risk, False, f"{getattr(manifest, 'action_class', plan.action_class)} action: {display}"
    return "low", False, "Default low risk"


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
                decision.risk_level = "high"
                decision.approval_required = True
                decision.reason = f"Dangerous command pattern detected: {dangerous_match}"
                decision.warnings.append("dangerous_command_requires_approval")
            else:
                risk_level, approval_required, reason = _base_risk_for_plan(plan, manifest)
                decision.risk_level = risk_level
                decision.approval_required = approval_required
                decision.reason = reason
            plan.risk_level = decision.risk_level
            _apply_conflict_risk(decision, plan, evidence_bundle)
            return decision

        # 1. Check for dangerous commands in arguments → critical, needs approval
        dangerous_match = _check_dangerous_commands(plan.arguments)
        if dangerous_match:
            decision.risk_level = "high"
            decision.approval_required = True
            decision.reason = f"Dangerous command pattern detected: {dangerous_match}"
            decision.warnings.append("dangerous_command_requires_approval")
            _apply_conflict_risk(decision, plan, evidence_bundle)
            plan.risk_level = decision.risk_level
            return decision

        # 2. Shell/python/powershell execute → medium (default: assume moderate risk)
        #    Approval only triggers for dangerous patterns caught above.
        if _is_execute_tool(plan.tool_id) or plan.action_class == "execute":
            decision.risk_level = "medium"
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
            if _is_destructive_action(plan):
                decision.risk_level = "high"
                decision.approval_required = True
                decision.reason = "Destructive action requires approval"
            else:
                decision.risk_level = "medium"
                decision.reason = "Mutating operation"
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
