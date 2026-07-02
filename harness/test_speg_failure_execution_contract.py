"""SPEG Failure Execution Contract — STOP/DEGRADE/RETRY have concrete
side effects and state constraints.
"""

import pytest
from types import SimpleNamespace

from speg_engine.failure_execution_contract import (
    FailureExecutionContract,
    apply_stop_contract,
    apply_degrade_contract,
    apply_retry_contract,
)
from speg_engine.runtime_stability import (
    IssueCollector,
    Severity,
    IssueCategory,
    SystemUnstableError,
)
from speg_engine.failure_semantics import FailureContext


def _ctx():
    return SimpleNamespace(extras={})


class TestStopContract:
    """STOP: terminal, no DAG, frozen context."""

    def test_stop_freezes_context(self):
        ctx = _ctx()
        result = apply_stop_contract(ctx)
        assert result["dag_executed"] is False
        assert result["context_frozen"] is True
        assert ctx.extras["execution_state"] == "TERMINAL"

    def test_stop_disables_dag(self):
        ctx = _ctx()
        apply_stop_contract(ctx)
        assert ctx.extras["dag_execution_allowed"] is False

    def test_stop_audit_flush(self):
        ctx = _ctx()
        result = apply_stop_contract(ctx)
        assert result["audit_flush_required"] is True

    def test_stop_raises_on_null_context(self):
        with pytest.raises(AssertionError):
            apply_stop_contract(None)


class TestDegradeContract:
    """DEGRADE: partial DAG, failed nodes skipped."""

    def test_degrade_allows_dag(self):
        ctx = _ctx()
        fctx = _make_fctx()
        result = apply_degrade_contract(ctx, fctx)
        assert result["dag_executed"] is True
        assert result["partial_execution"] is True

    def test_degrade_skips_failed(self):
        ctx = _ctx()
        fctx = _make_fctx()
        result = apply_degrade_contract(ctx, fctx)
        assert result["skip_failed_nodes"] is True
        assert ctx.extras["skip_failed_nodes"] is True

    def test_degrade_state(self):
        ctx = _ctx()
        fctx = _make_fctx()
        apply_degrade_contract(ctx, fctx)
        assert ctx.extras["execution_state"] == "DEGRADED"
        assert ctx.extras["context_frozen"] is False

    def test_degrade_raises_on_null_context(self):
        with pytest.raises(AssertionError):
            apply_degrade_contract(None, _make_fctx())


class TestRetryContract:
    """RETRY_SESSION: reset execution layer, re-plan."""

    def test_retry_resets_tool_state(self):
        ctx = _ctx()
        fctx = _make_fctx()
        result = apply_retry_contract(ctx, fctx)
        assert result["tool_state_reset"] is True
        assert ctx.extras["tool_state_reset"] is True

    def test_retry_requires_planner_re_run(self):
        ctx = _ctx()
        fctx = _make_fctx()
        result = apply_retry_contract(ctx, fctx)
        assert result["planner_re_run"] is True

    def test_retry_increments_counter(self):
        ctx = _ctx()
        fctx = _make_fctx()
        result = apply_retry_contract(ctx, fctx)
        assert result["retry_count"] == 1
        # Second call should increment
        result2 = apply_retry_contract(ctx, fctx)
        assert result2["retry_count"] == 2

    def test_retry_preserves_context(self):
        ctx = _ctx()
        fctx = _make_fctx()
        result = apply_retry_contract(ctx, fctx)
        assert result["context_preserved"] is True
        assert ctx.extras["context_snapshot_preserved"] is True

    def test_retry_state(self):
        ctx = _ctx()
        fctx = _make_fctx()
        apply_retry_contract(ctx, fctx)
        assert ctx.extras["execution_state"] == "RETRYING"

    def test_retry_raises_on_null_context(self):
        with pytest.raises(AssertionError):
            apply_retry_contract(None, _make_fctx())


class TestFullContractCoverage:
    """All 3 behaviors have execution contracts."""

    def test_all_behaviors_covered(self):
        from speg_engine.failure_semantics import FailurePolicy
        for key, val in FailurePolicy.AFTER_ABORT_BEHAVIOR.items():
            assert val in ("STOP", "DEGRADE", "RETRY_SESSION"), (
                f"Behavior '{val}' for '{key}' has no execution contract"
            )

    def test_stop_never_allows_dag(self):
        for _ in range(5):
            ctx = _ctx()
            result = apply_stop_contract(ctx)
            assert result["dag_executed"] is False

    def test_retry_counter_monotonic(self):
        ctx = _ctx()
        fctx = _make_fctx()
        prev = 0
        for _ in range(3):
            result = apply_retry_contract(ctx, fctx)
            assert result["retry_count"] > prev
            prev = result["retry_count"]


def _make_fctx():
    c = IssueCollector()
    err = SystemUnstableError(c)
    return FailureContext(err, c)
