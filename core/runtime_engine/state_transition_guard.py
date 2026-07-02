"""
SSOT Runtime v9 State Transition Guard — hardened with unknown-state
detection, no-op rejection, and single-write state management.
"""

from __future__ import annotations

from typing import Any


# ===========================================================================
# State machine definition
# ===========================================================================


VALID_STATES = ("RUNNING", "DEGRADED", "RETRYING", "TERMINAL")

VALID_TRANSITIONS: dict[str, list[str]] = {
    "RUNNING":   ["DEGRADED", "TERMINAL", "RETRYING"],
    "DEGRADED":  ["DEGRADED", "TERMINAL"],
    "RETRYING":  ["RETRYING", "RUNNING", "TERMINAL"],
    "TERMINAL":  [],
}

MAX_RETRY_SESSION: int = 1
MAX_DEGRADE_DEPTH: int = 1


class UnknownStateError(Exception):
    """A state not registered in VALID_TRANSITIONS was referenced."""
    def __init__(self, state: str):
        super().__init__(f"Unknown execution state: '{state}'")


class InvalidStateTransitionError(Exception):
    """Attempted an illegal state transition."""
    def __init__(self, from_state: str, to_state: str):
        super().__init__(f"{from_state} -> {to_state} not allowed")
        self.from_state = from_state
        self.to_state = to_state


class RetryBudgetExceededError(Exception):
    """Session retry count exceeded MAX_RETRY_SESSION."""
    def __init__(self, count: int):
        super().__init__(f"Retry budget exceeded: {count} > {MAX_RETRY_SESSION}")


class TerminalReEntryError(Exception):
    """Attempted to leave TERMINAL state."""
    def __init__(self):
        super().__init__("Terminal re-entry blocked — cannot leave TERMINAL")


class StateMutationError(Exception):
    """Attempted to mutate a finalized execution state."""
    def __init__(self):
        super().__init__("Execution state is finalized; no further mutations allowed")


class NoOpTransitionError(Exception):
    """Attempted a no-op state transition (from == to)."""
    def __init__(self, state: str):
        super().__init__(f"No-op transition: {state} -> {state}")


# ===========================================================================
# v9: Single-write ExecutionStateManager
# ===========================================================================


class ExecutionStateManager:
    """Single-write state manager — prevents multi-module overwrites.

    Once ``finalize()`` is called, no further state changes are allowed.
    """

    @staticmethod
    def set_state(ctx: Any, new_state: str) -> None:
        if ctx.extras.get("execution_state_finalized"):
            raise StateMutationError()
        prev = ctx.extras.get("execution_state", "RUNNING")
        ctx.extras["execution_state_prev"] = prev
        ctx.extras["execution_state"] = new_state
        # Record history
        history = ctx.extras.get("state_history", [])
        history.append({"from": prev, "to": new_state})
        ctx.extras["state_history"] = history

    @staticmethod
    def finalize(ctx: Any) -> None:
        ctx.extras["execution_state_finalized"] = True

    @staticmethod
    def set_field(ctx: Any, key: str, value: Any) -> None:
        """v9: typed context field writer — prevents free-form mutation."""
        if ctx.extras.get("execution_state_finalized") and key.startswith("execution"):
            raise StateMutationError()
        ctx.extras[key] = value


# ===========================================================================
# v9: ExecutionContextSchema — allowed keys
# ===========================================================================


EXECUTION_CONTEXT_KEYS = frozenset({
    "execution_state",
    "execution_state_prev",
    "execution_state_finalized",
    "dag_execution_allowed",
    "context_frozen",
    "session_retry_count",
    "tool_state_reset",
    "planner_re_run_required",
    "degrade_depth",
    "state_history",
    "skip_failed_nodes",
    "context_snapshot_preserved",
})


# ===========================================================================
# v9: RetryScope
# ===========================================================================


class RetryScope:
    """Explicit retry scope — no implicit inference."""
    PLANNER_ONLY = "PLANNER_ONLY"
    TOOL_ONLY = "TOOL_ONLY"
    FULL_REEXECUTION = "FULL_REEXECUTION"

    VALID = (PLANNER_ONLY, TOOL_ONLY, FULL_REEXECUTION)


# ===========================================================================
# State Transition Guard (v9 hardened)
# ===========================================================================


class StateTransitionGuard:
    """Enforces valid state transitions and prevents illegal paths."""

    @staticmethod
    def validate_transition(from_state: str, to_state: str) -> None:
        """v9: strict — unknown states are hard errors."""
        if from_state not in VALID_TRANSITIONS:
            raise UnknownStateError(from_state)
        if to_state not in VALID_TRANSITIONS:
            raise UnknownStateError(to_state)
        allowed = VALID_TRANSITIONS[from_state]
        if to_state not in allowed:
            raise InvalidStateTransitionError(from_state, to_state)

    @staticmethod
    def validate_no_terminal_reentry(ctx: Any) -> None:
        prev = ctx.extras.get("execution_state_prev", "")
        curr = ctx.extras.get("execution_state", "")
        if prev == "TERMINAL" and curr != "TERMINAL":
            raise TerminalReEntryError()

    @staticmethod
    def validate_retry_budget(ctx: Any) -> None:
        count = ctx.extras.get("session_retry_count", 0)
        if count > MAX_RETRY_SESSION:
            raise RetryBudgetExceededError(count)

    @staticmethod
    def validate_degrade_depth(ctx: Any) -> str | None:
        depth = ctx.extras.get("degrade_depth", 0)
        ctx.extras["degrade_depth"] = depth + 1
        if depth >= MAX_DEGRADE_DEPTH:
            return "TERMINAL"
        return None

    @staticmethod
    def transition(ctx: Any, to_state: str) -> None:
        """v9: atomic state change with full validation chain."""
        # v9: no-op detection
        prev = ctx.extras.get("execution_state", "RUNNING")
        if prev == to_state and prev != "DEGRADED" and prev != "RETRYING":
            raise NoOpTransitionError(prev)

        StateTransitionGuard.validate_no_terminal_reentry(ctx)
        StateTransitionGuard.validate_retry_budget(ctx)

        if to_state == "DEGRADED":
            forced = StateTransitionGuard.validate_degrade_depth(ctx)
            if forced:
                to_state = forced

        StateTransitionGuard.validate_transition(prev, to_state)
        ExecutionStateManager.set_state(ctx, to_state)

    @staticmethod
    def validate_chain(history: list[dict]) -> None:
        for entry in history:
            StateTransitionGuard.validate_transition(
                entry["from"], entry["to"]
            )


# ===========================================================================
# v9: Unified Execution Validator Pipeline
# ===========================================================================


class ExecutionValidatorPipeline:
    """v9: single entry point for all validation — no bypass allowed."""

    @staticmethod
    def validate(ctx: Any) -> None:
        """Run the full validation pipeline.  Called once per turn."""
        _validate_context_schema(ctx)
        _validate_state_consistency(ctx)
        StateTransitionGuard.validate_chain(
            ctx.extras.get("state_history", [])
        )


def _validate_context_schema(ctx: Any) -> None:
    """v9: context keys must be in EXECUTION_CONTEXT_KEYS."""
    unknown = set(ctx.extras.keys()) - EXECUTION_CONTEXT_KEYS
    # Allow extras that are NOT execution-control keys
    execution_keys = {k for k in ctx.extras
                      if k.startswith("execution_")
                      or k in ("dag_execution_allowed", "context_frozen",
                               "session_retry_count", "tool_state_reset",
                               "degrade_depth", "state_history",
                               "skip_failed_nodes", "context_snapshot_preserved",
                               "planner_re_run_required")}
    unknown_exec = unknown & execution_keys
    if unknown_exec:
        raise AssertionError(
            f"Unknown execution context keys: {sorted(unknown_exec)}"
        )


def _validate_state_consistency(ctx: Any) -> None:
    """v9: terminal consistency check."""
    state = ctx.extras.get("execution_state", "RUNNING")
    assert state in VALID_STATES, f"Unknown execution state: {state}"
    if state == "TERMINAL":
        assert ctx.extras.get("dag_execution_allowed") is False
    StateTransitionGuard.validate_no_terminal_reentry(ctx)


# Keep backward-compatible alias
def validate_state_consistency(ctx: Any) -> None:
    _validate_state_consistency(ctx)


__all__ = [
    "VALID_STATES",
    "VALID_TRANSITIONS",
    "MAX_RETRY_SESSION",
    "MAX_DEGRADE_DEPTH",
    "EXECUTION_CONTEXT_KEYS",
    "StateTransitionGuard",
    "ExecutionStateManager",
    "ExecutionValidatorPipeline",
    "RetryScope",
    "InvalidStateTransitionError",
    "RetryBudgetExceededError",
    "TerminalReEntryError",
    "UnknownStateError",
    "StateMutationError",
    "NoOpTransitionError",
    "validate_state_consistency",
]
