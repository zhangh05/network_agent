"""
SPEG v8 State Transition Guard — prevents illegal state jumps,
infinite retry loops, and terminal re-entry.

This is a constraint layer on top of the v7 Failure Execution FSM.
It does NOT modify existing Policy / Contract / Execution logic.
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
    "TERMINAL":  [],   # final state — no outgoing transitions
}

MAX_RETRY_SESSION: int = 1
MAX_DEGRADE_DEPTH: int = 1


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


# ===========================================================================
# State Transition Guard
# ===========================================================================


class StateTransitionGuard:
    """Enforces valid state transitions and prevents illegal paths."""

    @staticmethod
    def validate_transition(from_state: str, to_state: str) -> None:
        """Raise InvalidStateTransitionError if the transition is illegal."""
        allowed = VALID_TRANSITIONS.get(from_state, [])
        if to_state not in allowed:
            raise InvalidStateTransitionError(from_state, to_state)

    @staticmethod
    def validate_no_terminal_reentry(ctx: Any) -> None:
        """Block any attempt to leave TERMINAL."""
        prev = ctx.extras.get("execution_state_prev", "")
        curr = ctx.extras.get("execution_state", "")
        if prev == "TERMINAL" and curr != "TERMINAL":
            raise TerminalReEntryError()

    @staticmethod
    def validate_retry_budget(ctx: Any) -> None:
        """Block retry if budget exceeded."""
        count = ctx.extras.get("session_retry_count", 0)
        if count > MAX_RETRY_SESSION:
            raise RetryBudgetExceededError(count)

    @staticmethod
    def validate_degrade_depth(ctx: Any) -> str | None:
        """Enforce degrade depth limit; return "TERMINAL" if exceeded."""
        depth = ctx.extras.get("degrade_depth", 0)
        ctx.extras["degrade_depth"] = depth + 1
        if depth >= MAX_DEGRADE_DEPTH:
            return "TERMINAL"
        return None

    @staticmethod
    def transition(ctx: Any, to_state: str) -> None:
        """Perform a validated state transition.

        Records the previous state, validates the transition,
        enforces terminal re-entry, retry budget, and degrade depth.
        Updates ctx.extras atomically.
        """
        prev = ctx.extras.get("execution_state", "RUNNING")

        # Terminal re-entry check
        StateTransitionGuard.validate_no_terminal_reentry(ctx)

        # Retry budget check
        StateTransitionGuard.validate_retry_budget(ctx)

        # Degrade depth check
        if to_state == "DEGRADED":
            forced = StateTransitionGuard.validate_degrade_depth(ctx)
            if forced:
                to_state = forced

        # Validate the transition
        StateTransitionGuard.validate_transition(prev, to_state)

        # Record history
        history = ctx.extras.get("state_history", [])
        history.append({"from": prev, "to": to_state})
        ctx.extras["state_history"] = history

        # Apply
        ctx.extras["execution_state_prev"] = prev
        ctx.extras["execution_state"] = to_state

    @staticmethod
    def validate_chain(history: list[dict]) -> None:
        """Validate that an entire state history chain is legal."""
        for entry in history:
            StateTransitionGuard.validate_transition(
                entry["from"], entry["to"]
            )


# ===========================================================================
# Context State Consistency Check
# ===========================================================================


def validate_state_consistency(ctx: Any) -> None:
    """Final consistency check before the turn result is returned."""
    state = ctx.extras.get("execution_state", "RUNNING")
    assert state in VALID_STATES, f"Unknown execution state: {state}"

    if state == "TERMINAL":
        assert ctx.extras.get("dag_execution_allowed") is False, (
            "TERMINAL state must not allow DAG execution"
        )

    # If previous state was TERMINAL, current must also be TERMINAL
    StateTransitionGuard.validate_no_terminal_reentry(ctx)


__all__ = [
    "VALID_STATES",
    "VALID_TRANSITIONS",
    "MAX_RETRY_SESSION",
    "MAX_DEGRADE_DEPTH",
    "StateTransitionGuard",
    "InvalidStateTransitionError",
    "RetryBudgetExceededError",
    "TerminalReEntryError",
    "validate_state_consistency",
]
