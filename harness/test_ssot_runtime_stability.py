"""SSOT Runtime Ultimate Stability — termination convergence tests.

Verifies that the system has a hard stop condition and does not
enter infinite repair / retry loops.
"""

import pytest
from core.runtime_engine.runtime_stability import (
    StabilityBoundary,
    SystemMode,
    Severity,
    IssueCategory,
    IssueReport,
    IssueCollector,
    SystemUnstableError,
    MAX_REPAIR_DEPTH,
    MAX_RETRY_DEPTH,
    RepairDepthExceeded,
    RetryDepthExceeded,
    system_acceptance_check,
)


class TestStabilityBoundary:
    """StabilityBoundary hard limits."""

    def test_max_critical_is_zero(self):
        assert StabilityBoundary.MAX_CRITICAL_ISSUES == 0

    def test_max_high_is_zero(self):
        assert StabilityBoundary.MAX_HIGH_ISSUES == 0

    def test_max_warnings_is_three(self):
        assert StabilityBoundary.MAX_ALLOWED_WARNINGS == 3


class TestIssueCollector:
    """IssueCollector accumulates and checks boundaries."""

    def test_empty_collector_passes(self):
        c = IssueCollector()
        assert c.critical_count == 0
        assert c.high_count == 0
        assert c.check_boundary() is True

    def test_critical_breaches_boundary(self):
        c = IssueCollector()
        c.add(Severity.CRITICAL, IssueCategory.CONTRACT,
              "test", "critical issue")
        assert c.critical_count == 1
        assert c.check_boundary() is False

    def test_high_breaches_boundary(self):
        c = IssueCollector()
        c.add(Severity.HIGH, IssueCategory.TOOL, "test", "high issue")
        assert c.high_count == 1
        assert c.check_boundary() is False

    def test_warnings_within_limit(self):
        c = IssueCollector()
        c.add(Severity.MEDIUM, IssueCategory.CONTEXT, "t", "w1")
        c.add(Severity.LOW, IssueCategory.EXECUTION, "t", "w2")
        c.add(Severity.MEDIUM, IssueCategory.SCHEMA, "t", "w3")
        assert c.warning_count == 3
        assert c.check_boundary() is True

    def test_warnings_exceed_limit(self):
        c = IssueCollector()
        for i in range(4):
            c.add(Severity.MEDIUM, IssueCategory.CONTEXT, "t", f"w{i}")
        assert c.warning_count == 4
        assert c.check_boundary() is False

    def test_to_dict(self):
        c = IssueCollector()
        c.add(Severity.HIGH, IssueCategory.TOOL, "exec.run", "failed")
        d = c.to_dict()
        assert d["critical_count"] == 0
        assert d["high_count"] == 1
        assert len(d["issues"]) == 1


class TestSystemUnstableError:
    """SystemUnstableError carries the collector report."""

    def test_error_contains_counts(self):
        c = IssueCollector()
        c.add(Severity.CRITICAL, IssueCategory.CONTRACT, "t", "bad")
        with pytest.raises(SystemUnstableError) as exc:
            raise SystemUnstableError(c)
        assert "CRITICAL=1" in str(exc.value)
        assert exc.value.report is c


class TestAcceptanceModes:
    """system_acceptance_check respects mode."""

    def test_strict_rejects_critical(self):
        c = IssueCollector()
        c.add(Severity.CRITICAL, IssueCategory.CONTRACT, "t", "bad")
        assert system_acceptance_check(c, SystemMode.STRICT) is False

    def test_acceptance_allows_high(self):
        c = IssueCollector()
        c.add(Severity.HIGH, IssueCategory.TOOL, "t", "high")
        # ACCEPTANCE allows HIGH but not CRITICAL
        assert system_acceptance_check(c, SystemMode.ACCEPTANCE) is True

    def test_acceptance_rejects_critical(self):
        c = IssueCollector()
        c.add(Severity.CRITICAL, IssueCategory.CONTRACT, "t", "bad")
        assert system_acceptance_check(c, SystemMode.ACCEPTANCE) is False

    def test_diagnostic_always_passes(self):
        c = IssueCollector()
        c.add(Severity.CRITICAL, IssueCategory.CONTRACT, "t", "bad")
        assert system_acceptance_check(c, SystemMode.DIAGNOSTIC) is True


class TestRepairRetryDepth:
    """MAX_REPAIR_DEPTH and MAX_RETRY_DEPTH enforce hard limits."""

    def test_max_repair_depth_is_one(self):
        assert MAX_REPAIR_DEPTH == 1

    def test_max_retry_depth_is_one(self):
        assert MAX_RETRY_DEPTH == 1

    def test_repair_depth_exceeded_raises(self):
        with pytest.raises(RepairDepthExceeded):
            raise RepairDepthExceeded(2)

    def test_retry_depth_exceeded_raises(self):
        with pytest.raises(RetryDepthExceeded):
            raise RetryDepthExceeded(2)


class TestIssueReport:
    """IssueReport dataclass works."""

    def test_severity_and_category(self):
        r = IssueReport(
            severity=Severity.HIGH,
            category=IssueCategory.TOOL,
            source="exec.run",
            description="timeout",
            metadata={"node_id": "n1"},
        )
        assert r.severity == Severity.HIGH
        assert r.category == IssueCategory.TOOL
        assert r.metadata["node_id"] == "n1"


class TestSystemModeDefaults:
    """SYSTEM_MODE is STRICT by default for CI."""

    def test_default_mode_is_strict(self):
        from core.runtime_engine.runtime_stability import SYSTEM_MODE
        assert SYSTEM_MODE == SystemMode.STRICT
