"""SSOT Runtime v8 State Transition Guard — prevents illegal state transitions,
infinite retry loops, and terminal re-entry.
"""

import pytest
from types import SimpleNamespace

from core.runtime_engine.state_transition_guard import (
    VALID_STATES,
    VALID_TRANSITIONS,
    MAX_RETRY_SESSION,
    MAX_DEGRADE_DEPTH,
    StateTransitionGuard,
    InvalidStateTransitionError,
    RetryBudgetExceededError,
    TerminalReEntryError,
    validate_state_consistency,
)


def _ctx(state="RUNNING", **extras):
    d = {"execution_state": state, **extras}
    return SimpleNamespace(extras=d)


class TestValidTransitions:
    """Only defined transitions are allowed."""

    def test_running_to_degraded(self):
        StateTransitionGuard.validate_transition("RUNNING", "DEGRADED")  # ok

    def test_running_to_terminal(self):
        StateTransitionGuard.validate_transition("RUNNING", "TERMINAL")  # ok

    def test_running_to_retrying(self):
        StateTransitionGuard.validate_transition("RUNNING", "RETRYING")  # ok

    def test_terminal_has_no_outgoing(self):
        assert VALID_TRANSITIONS["TERMINAL"] == []

    def test_degraded_to_running_blocked(self):
        with pytest.raises(InvalidStateTransitionError):
            StateTransitionGuard.validate_transition("DEGRADED", "RUNNING")

    def test_retrying_to_retrying_allowed(self):
        StateTransitionGuard.validate_transition("RETRYING", "RETRYING")  # ok

    def test_retrying_to_degraded_blocked(self):
        with pytest.raises(InvalidStateTransitionError):
            StateTransitionGuard.validate_transition("RETRYING", "DEGRADED")

    def test_valid_states_are_four(self):
        assert len(VALID_STATES) == 4
        assert "RUNNING" in VALID_STATES
        assert "TERMINAL" in VALID_STATES


class TestTerminalReentry:
    """TERMINAL cannot be left."""

    def test_terminal_to_running_blocked(self):
        ctx = _ctx(execution_state="TERMINAL",
                   execution_state_prev="TERMINAL")
        ctx.extras["execution_state"] = "RUNNING"
        with pytest.raises(TerminalReEntryError):
            StateTransitionGuard.validate_no_terminal_reentry(ctx)

    def test_terminal_to_retry_blocked(self):
        ctx = _ctx(execution_state="RETRYING",
                   execution_state_prev="TERMINAL")
        with pytest.raises(TerminalReEntryError):
            StateTransitionGuard.validate_no_terminal_reentry(ctx)

    def test_terminal_stay_terminal_ok(self):
        ctx = _ctx(execution_state="TERMINAL",
                   execution_state_prev="TERMINAL")
        StateTransitionGuard.validate_no_terminal_reentry(ctx)  # ok


class TestRetryBudget:
    """RETRY is capped at MAX_RETRY_SESSION."""

    def test_retry_within_budget(self):
        ctx = _ctx(session_retry_count=1)
        StateTransitionGuard.validate_retry_budget(ctx)  # ok

    def test_retry_exceeded(self):
        ctx = _ctx(session_retry_count=2)
        with pytest.raises(RetryBudgetExceededError):
            StateTransitionGuard.validate_retry_budget(ctx)

    def test_max_retry_is_one(self):
        assert MAX_RETRY_SESSION == 1


class TestDegradeDepth:
    """DEGRADE loop auto-escalates to TERMINAL."""

    def test_degrade_depth_enforced(self):
        assert MAX_DEGRADE_DEPTH == 1

    def test_degrade_exceeded_returns_terminal(self):
        ctx = _ctx(degrade_depth=1)
        forced = StateTransitionGuard.validate_degrade_depth(ctx)
        assert forced == "TERMINAL"

    def test_degrade_within_limit(self):
        ctx = _ctx(degrade_depth=0)
        forced = StateTransitionGuard.validate_degrade_depth(ctx)
        assert forced is None
        assert ctx.extras["degrade_depth"] == 1


class TestTransitionMethod:
    """StateTransitionGuard.transition() full pipeline."""

    def test_transition_creates_history(self):
        ctx = _ctx()
        StateTransitionGuard.transition(ctx, "DEGRADED")
        history = ctx.extras["state_history"]
        assert len(history) == 1
        assert history[0]["from"] == "RUNNING"
        assert history[0]["to"] == "DEGRADED"

    def test_transition_sets_prev(self):
        ctx = _ctx()
        StateTransitionGuard.transition(ctx, "DEGRADED")
        assert ctx.extras["execution_state_prev"] == "RUNNING"
        assert ctx.extras["execution_state"] == "DEGRADED"

    def test_degrade_loop_forces_terminal(self):
        ctx = _ctx()
        StateTransitionGuard.transition(ctx, "DEGRADED")  # depth 0 -> 1 -> allowed
        ctx.extras["execution_state_prev"] = "DEGRADED"
        # Second DEGRADE: depth 1 >= MAX_DEGRADE_DEPTH(1) -> TERMINAL
        StateTransitionGuard.transition(ctx, "DEGRADED")
        assert ctx.extras["execution_state"] == "TERMINAL"

    def test_retry_blocked_by_budget(self):
        ctx = _ctx(session_retry_count=2)
        with pytest.raises(RetryBudgetExceededError):
            StateTransitionGuard.transition(ctx, "RETRYING")

    def test_terminal_cannot_transition_out(self):
        ctx = _ctx(execution_state="TERMINAL",
                   execution_state_prev="TERMINAL")
        # The FSM transition guard catches this first as
        # InvalidStateTransitionError (TERMINAL has no outgoing transitions).
        with pytest.raises(InvalidStateTransitionError):
            StateTransitionGuard.transition(ctx, "RUNNING")


class TestValidateChain:
    """Validate complete state history."""

    def test_valid_chain(self):
        history = [
            {"from": "RUNNING", "to": "DEGRADED"},
            {"from": "DEGRADED", "to": "TERMINAL"},
        ]
        StateTransitionGuard.validate_chain(history)  # ok

    def test_invalid_chain(self):
        history = [
            {"from": "RUNNING", "to": "DEGRADED"},
            {"from": "DEGRADED", "to": "RUNNING"},  # illegal
        ]
        with pytest.raises(InvalidStateTransitionError):
            StateTransitionGuard.validate_chain(history)


class TestStateConsistency:
    """validate_state_consistency final gate."""

    def test_running_ok(self):
        ctx = _ctx(execution_state="RUNNING")
        validate_state_consistency(ctx)  # ok

    def test_terminal_requires_dag_disabled(self):
        ctx = _ctx(execution_state="TERMINAL",
                   dag_execution_allowed=True)
        with pytest.raises(AssertionError):
            validate_state_consistency(ctx)

    def test_terminal_dag_off(self):
        ctx = _ctx(execution_state="TERMINAL",
                   dag_execution_allowed=False)
        validate_state_consistency(ctx)  # ok

    def test_unknown_state_fails(self):
        ctx = _ctx(execution_state="UNKNOWN")
        with pytest.raises(AssertionError):
            validate_state_consistency(ctx)

from core.runtime_engine.state_transition_guard import (
    UnknownStateError,
    StateMutationError,
    NoOpTransitionError,
    ExecutionStateManager,
    ExecutionValidatorPipeline,
    RetryScope,
)


class TestV9UnknownState:
    """v9: unknown states are hard errors."""

    def test_unknown_from_state_raises(self):
        with pytest.raises(UnknownStateError):
            StateTransitionGuard.validate_transition("MYSTERY", "RUNNING")

    def test_unknown_to_state_raises(self):
        with pytest.raises(UnknownStateError):
            StateTransitionGuard.validate_transition("RUNNING", "MYSTERY")


class TestV9NoOpTransition:
    """v9: no-op transitions are detected and rejected."""

    def test_running_to_running_blocked(self):
        ctx = _ctx()
        with pytest.raises(NoOpTransitionError):
            StateTransitionGuard.transition(ctx, "RUNNING")

    def test_terminal_to_terminal_blocked(self):
        ctx = _ctx(execution_state="TERMINAL",
                   execution_state_prev="TERMINAL")
        with pytest.raises(NoOpTransitionError):
            StateTransitionGuard.transition(ctx, "TERMINAL")


class TestV9StateMutationBlock:
    """v9: finalized state cannot be mutated."""

    def test_finalized_blocks_state_change(self):
        ctx = _ctx()
        ExecutionStateManager.finalize(ctx)
        with pytest.raises(StateMutationError):
            ExecutionStateManager.set_state(ctx, "DEGRADED")

    def test_finalized_blocks_execution_field(self):
        ctx = _ctx(execution_state_finalized=True)
        with pytest.raises(StateMutationError):
            ExecutionStateManager.set_field(ctx, "execution_state", "DEGRADED")

    def test_non_execution_field_allowed(self):
        ctx = _ctx(execution_state_finalized=True)
        ExecutionStateManager.set_field(ctx, "other_field", 42)
        assert ctx.extras["other_field"] == 42


class TestV9ExecutionValidatorPipeline:
    """v9: single validation entry point."""

    def test_pipeline_passes_on_clean_ctx(self):
        ctx = _ctx()
        ExecutionValidatorPipeline.validate(ctx)  # ok

    def test_pipeline_unknown_exec_key_raises(self):
        ctx = _ctx(execution_invalid=True)
        with pytest.raises(AssertionError):
            ExecutionValidatorPipeline.validate(ctx)


class TestV9RetryScope:
    """v9: explicit retry scope, no implicit inference."""

    def test_all_scopes_defined(self):
        assert RetryScope.PLANNER_ONLY == "PLANNER_ONLY"
        assert RetryScope.TOOL_ONLY == "TOOL_ONLY"
        assert RetryScope.FULL_REEXECUTION == "FULL_REEXECUTION"

    def test_scopes_are_valid(self):
        assert RetryScope.PLANNER_ONLY in RetryScope.VALID
        assert RetryScope.TOOL_ONLY in RetryScope.VALID
