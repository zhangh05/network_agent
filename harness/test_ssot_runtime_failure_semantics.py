"""SSOT Runtime Failure Semantics Closure — post-abort behavior is always defined.

Verifies that SystemUnstableError has explicit semantics:
  - STOP → terminal abort
  - DEGRADE → degraded continuation
  - RETRY_SESSION → retry scheduling
  - high/critical report → not recoverable
  - clean report → recoverable
"""

import pytest
from core.runtime_engine.runtime_stability import (
    IssueCollector,
    Severity,
    IssueCategory,
    SystemUnstableError,
)
from core.runtime_engine.failure_semantics import (
    FailurePolicy,
    FailureContext,
    degraded_result,
    retry_session_result,
)


class TestFailurePolicyMappings:
    """Every error type HAS a defined behavior."""

    def test_system_unstable_error_is_mapped(self):
        assert "SYSTEM_UNSTABLE_ERROR" in FailurePolicy.AFTER_ABORT_BEHAVIOR

    def test_default_behavior_is_stop(self):
        assert FailurePolicy.AFTER_ABORT_BEHAVIOR["SYSTEM_UNSTABLE_ERROR"] == "STOP"

    def test_behaviour_for_returns_correctly(self):
        assert FailurePolicy.behaviour_for("SYSTEM_UNSTABLE_ERROR") == "STOP"

    def test_unmapped_type_raises_keyerror(self):
        with pytest.raises(KeyError):
            FailurePolicy.behaviour_for("UNKNOWN_ERROR")

    def test_policy_is_not_none(self):
        assert FailurePolicy.AFTER_ABORT_BEHAVIOR is not None


class TestFailureContext:
    """FailureContext carries error, report, and recovery verdict."""

    def test_critical_makes_unrecoverable(self):
        c = IssueCollector()
        c.add(Severity.CRITICAL, IssueCategory.CONTRACT, "t", "critical")
        err = SystemUnstableError(c)
        fctx = FailureContext(err, c)
        assert fctx.recoverable is False

    def test_high_makes_unrecoverable(self):
        c = IssueCollector()
        c.add(Severity.HIGH, IssueCategory.TOOL, "t", "high")
        err = SystemUnstableError(c)
        fctx = FailureContext(err, c)
        assert fctx.recoverable is False

    def test_clean_report_is_recoverable(self):
        c = IssueCollector()
        err = SystemUnstableError(c)
        fctx = FailureContext(err, c)
        assert fctx.recoverable is True

    def test_to_dict_includes_error_type(self):
        c = IssueCollector()
        err = SystemUnstableError(c)
        fctx = FailureContext(err, c)
        d = fctx.to_dict()
        assert d["error_type"] == "SystemUnstableError"
        assert "error_message" in d


class TestDegradedResult:
    """degraded_result returns structured DEGRADED payload."""

    def test_degraded_has_status(self):
        c = IssueCollector()
        err = SystemUnstableError(c)
        fctx = FailureContext(err, c)
        result = degraded_result(fctx)
        assert result["status"] == "DEGRADED"
        assert "reason" in result

    def test_degraded_has_recoverable_flag(self):
        c = IssueCollector()
        c.add(Severity.CRITICAL, IssueCategory.CONTRACT, "t", "bad")
        err = SystemUnstableError(c)
        fctx = FailureContext(err, c)
        result = degraded_result(fctx)
        assert result["recoverable"] is False


class TestRetrySessionResult:
    """retry_session_result returns structured RETRY payload."""

    def test_retry_has_status(self):
        c = IssueCollector()
        err = SystemUnstableError(c)
        fctx = FailureContext(err, c)
        result = retry_session_result(fctx)
        assert result["status"] == "RETRY_SCHEDULED"
        assert "retry_allowed" in result

    def test_retry_blocked_for_critical(self):
        c = IssueCollector()
        c.add(Severity.CRITICAL, IssueCategory.CONTRACT, "t", "bad")
        err = SystemUnstableError(c)
        fctx = FailureContext(err, c)
        result = retry_session_result(fctx)
        assert result["retry_allowed"] is False

    def test_retry_allowed_for_clean(self):
        c = IssueCollector()
        err = SystemUnstableError(c)
        fctx = FailureContext(err, c)
        result = retry_session_result(fctx)
        assert result["retry_allowed"] is True


class TestFailureSemanticsContract:
    """FailureSemanticsContract flags are in place."""

    def test_must_define_post_abort(self):
        from core.runtime_engine.runtime_contracts import FailureSemanticsContract
        assert FailureSemanticsContract.MUST_DEFINE_POST_ABORT_BEHAVIOR is True

    def test_sue_is_not_hardcoded_terminal(self):
        from core.runtime_engine.runtime_contracts import FailureSemanticsContract
        assert FailureSemanticsContract.SYSTEM_UNSTABLE_ERROR_IS_TERMINAL is False

    def test_every_policy_key_is_valid_behavior(self):
        valid = {"STOP", "DEGRADE", "RETRY_SESSION"}
        for key, val in FailurePolicy.AFTER_ABORT_BEHAVIOR.items():
            assert val in valid, f"{key} -> '{val}' is not a valid behavior"


class TestFullFlowSTOP:
    """Integration: STOP behavior -> terminal result."""

    def test_system_unstable_error_carries_collector(self):
        c = IssueCollector()
        c.add(Severity.CRITICAL, IssueCategory.CONTRACT, "eng", "fatal")
        err = SystemUnstableError(c)
        assert err.report is c
        assert err.report.critical_count == 1
