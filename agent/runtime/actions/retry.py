# agent/runtime/actions/retry.py
"""RetryPolicy — decides if a failed action should be retried."""

from __future__ import annotations

from agent.runtime.actions.models import ActionPlan, ActionResult, RiskDecision


class RetryPolicy:
    """Decide whether a failed action should be retried."""

    def should_retry(self, plan: ActionPlan, result: ActionResult,
                     risk: RiskDecision) -> bool:
        """Return True if the action should be retried.

        Rules:
        - No auto-retry for high-risk execute actions.
        - Read/search actions can retry once.
        - Already retried (attempts >= 2) → no retry.
        - Blocked actions → no retry.
        """
        # Never retry blocked
        if result.status == "blocked" or risk.blocked:
            return False

        # Never retry if already tried twice
        if result.attempts >= 2:
            return False

        # No auto-retry for high-risk execute
        if plan.action_class == "execute" and risk.risk_level in ("high", "critical"):
            return False

        # Read/search can retry once
        if plan.action_class == "read" and result.attempts < 2:
            result.retryable = True
            return True

        return False
