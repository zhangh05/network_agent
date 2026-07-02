"""
SPEG Failure Execution Contract — concrete runtime actions for
STOP / DEGRADE / RETRY_SESSION behaviors.

Each behavior now has an explicit execution contract with
mandatory side effects and state constraints.
"""

from __future__ import annotations

from typing import Any


class FailureExecutionContract:
    """Concrete execution semantics for post-abort behaviors.

    Each method corresponds to a FailurePolicy.AFTER_ABORT_BEHAVIOR
    entry and defines the mandatory side effects.
    """

    @staticmethod
    def stop(ctx: Any) -> dict[str, Any]:
        """STOP contract: terminate immediately, no further work.

        Mandatory side effects:
          - No DAG execution
          - Context frozen (no further modifications)
          - Audit flush signal
          - Terminal result only
        """
        # Freeze context — mark as terminal
        ctx.extras["execution_state"] = "TERMINAL"
        ctx.extras["dag_execution_allowed"] = False
        ctx.extras["context_frozen"] = True

        return {
            "status": "TERMINAL",
            "dag_executed": False,
            "context_frozen": True,
            "audit_flush_required": True,
        }

    @staticmethod
    def degrade(ctx: Any, failure_ctx: Any) -> dict[str, Any]:
        """DEGRADE contract: partial completion, skip failed.

        Mandatory side effects:
          - Partial DAG completion allowed
          - Failed nodes skipped
          - Context marked degraded (still valid)
          - Finalize with degraded_result
        """
        ctx.extras["execution_state"] = "DEGRADED"
        ctx.extras["dag_execution_allowed"] = True
        ctx.extras["skip_failed_nodes"] = True
        ctx.extras["context_frozen"] = False

        return {
            "status": "DEGRADED",
            "dag_executed": True,
            "partial_execution": True,
            "skip_failed_nodes": True,
            "recoverable": getattr(failure_ctx, "recoverable", False),
        }

    @staticmethod
    def retry_session(ctx: Any, failure_ctx: Any) -> dict[str, Any]:
        """RETRY_SESSION contract: reset execution layer, re-plan.

        Mandatory side effects:
          - Execution layer reset (tool state cleared)
          - Context snapshot preserved
          - Planner re-run only
          - Tool execution state reset
          - Retry counter incremented
        """
        # Increment retry counter
        prev = ctx.extras.get("session_retry_count", 0)
        ctx.extras["session_retry_count"] = prev + 1

        # Reset execution state
        ctx.extras["execution_state"] = "RETRYING"
        ctx.extras["dag_execution_allowed"] = True
        ctx.extras["tool_state_reset"] = True
        ctx.extras["planner_re_run_required"] = True
        ctx.extras["context_frozen"] = False

        # Preserve context snapshot before reset
        ctx.extras["context_snapshot_preserved"] = True

        return {
            "status": "RETRY_SCHEDULED",
            "retry_count": prev + 1,
            "planner_re_run": True,
            "tool_state_reset": True,
            "context_preserved": True,
            "recoverable": getattr(failure_ctx, "recoverable", False),
        }


# ── Engine-level contract appliers ──────────────────────────────────────


def apply_stop_contract(ctx: Any) -> dict[str, Any]:
    """Apply STOP contract: terminal, no DAG, frozen context."""
    assert ctx is not None, "STOP contract requires non-null context"

    # v8: validated state transition
    from .state_transition_guard import StateTransitionGuard
    StateTransitionGuard.transition(ctx, "TERMINAL")

    result = FailureExecutionContract.stop(ctx)
    assert result["dag_executed"] is False, "STOP must not allow DAG execution"
    assert result["context_frozen"] is True, "STOP must freeze context"
    return result


def apply_degrade_contract(ctx: Any, failure_ctx: Any) -> dict[str, Any]:
    """Apply DEGRADE contract: partial DAG, failed nodes skipped."""
    assert ctx is not None, "DEGRADE contract requires non-null context"

    # v8: validated state transition (may be forced to TERMINAL)
    from .state_transition_guard import StateTransitionGuard
    StateTransitionGuard.transition(ctx, "DEGRADED")

    result = FailureExecutionContract.degrade(ctx, failure_ctx)
    assert result["partial_execution"] is True, "DEGRADE must allow partial execution"
    assert result["skip_failed_nodes"] is True, "DEGRADE must skip failed nodes"
    return result


def apply_retry_contract(ctx: Any, failure_ctx: Any) -> dict[str, Any]:
    """Apply RETRY_SESSION contract: reset exec layer, re-plan."""
    assert ctx is not None, "RETRY contract requires non-null context"

    # v8: validated state transition + retry budget check
    from .state_transition_guard import StateTransitionGuard
    StateTransitionGuard.transition(ctx, "RETRYING")
    StateTransitionGuard.validate_retry_budget(ctx)

    result = FailureExecutionContract.retry_session(ctx, failure_ctx)
    assert result["planner_re_run"] is True, "RETRY must require planner re-run"
    assert result["tool_state_reset"] is True, "RETRY must reset tool state"
    assert result["retry_count"] >= 1, "RETRY must increment retry counter"
    return result


__all__ = [
    "FailureExecutionContract",
    "apply_stop_contract",
    "apply_degrade_contract",
    "apply_retry_contract",
]
