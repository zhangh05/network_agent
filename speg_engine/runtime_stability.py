"""
SPEG Ultimate Stability — system termination convergence mechanism.

Prevents infinite repair loops by establishing hard boundaries on
issue counts and repair depth. Every runtime issue is classified and
counted; when the boundary is breached, the system hard-stops.

Design principle: a system that endlessly repairs itself is not
stable. This module is the stop condition.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


# ===========================================================================
# Stability Boundary
# ===========================================================================


class StabilityBoundary:
    """Hard limits on issue counts. Breaching any limit is a system failure."""

    MAX_CRITICAL_ISSUES: int = 0
    MAX_HIGH_ISSUES: int = 0
    MAX_ALLOWED_WARNINGS: int = 3


class SystemMode(enum.Enum):
    STRICT = "strict"           # All boundaries enforced; CI mode
    DIAGNOSTIC = "diagnostic"   # Collect only, no abort
    ACCEPTANCE = "acceptance"   # HIGH warnings allowed, no CRITICAL


# Default mode for CI.
SYSTEM_MODE: SystemMode = SystemMode.STRICT


# ===========================================================================
# Issue Classifier
# ===========================================================================


class Severity(enum.Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class IssueCategory(enum.Enum):
    TOOL = "TOOL"
    CONTEXT = "CONTEXT"
    SCHEMA = "SCHEMA"
    EXECUTION = "EXECUTION"
    CONTRACT = "CONTRACT"


@dataclass
class IssueReport:
    """Single classified runtime issue."""
    severity: Severity
    category: IssueCategory
    source: str         # module path
    description: str
    metadata: dict[str, Any] = field(default_factory=dict)


# ===========================================================================
# Collective Issue Tracker
# ===========================================================================


class IssueCollector:
    """Per-turn issue collector. Accumulated and checked at the end."""

    def __init__(self):
        self._issues: list[IssueReport] = []

    def add(self, severity: Severity, category: IssueCategory,
            source: str, description: str, **meta) -> None:
        self._issues.append(IssueReport(
            severity=severity, category=category,
            source=source, description=description,
            metadata=dict(meta),
        ))

    @property
    def issues(self) -> list[IssueReport]:
        return list(self._issues)

    @property
    def critical_count(self) -> int:
        return sum(1 for i in self._issues if i.severity == Severity.CRITICAL)

    @property
    def high_count(self) -> int:
        return sum(1 for i in self._issues if i.severity == Severity.HIGH)

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self._issues
                   if i.severity in (Severity.MEDIUM, Severity.LOW))

    def check_boundary(self, boundary: type[StabilityBoundary] | None = None) -> bool:
        """Return True if all boundaries are within limits."""
        b = boundary or StabilityBoundary
        if self.critical_count > b.MAX_CRITICAL_ISSUES:
            return False
        if self.high_count > b.MAX_HIGH_ISSUES:
            return False
        if self.warning_count > b.MAX_ALLOWED_WARNINGS:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "critical_count": self.critical_count,
            "high_count": self.high_count,
            "warning_count": self.warning_count,
            "total_issues": len(self._issues),
            "issues": [
                {
                    "severity": i.severity.value,
                    "category": i.category.value,
                    "source": i.source,
                    "description": i.description,
                }
                for i in self._issues
            ],
        }


# ===========================================================================
# System Unstable Error — terminal stop condition
# ===========================================================================


class SystemUnstableError(Exception):
    """Raised when the stability boundary is breached.

    This is the terminal stop condition. No retry, no repair, no
    fallback — the system MUST abort the current turn.
    """

    def __init__(self, report: IssueCollector):
        self.report = report
        super().__init__(
            f"System stability boundary breached: "
            f"CRITICAL={report.critical_count} "
            f"HIGH={report.high_count} "
            f"WARNINGS={report.warning_count}"
        )


# ===========================================================================
# Repair / Retry depth enforcement
# ===========================================================================

MAX_REPAIR_DEPTH: int = 1
MAX_RETRY_DEPTH: int = 1


class RepairDepthExceeded(Exception):
    """Repair chain exceeded MAX_REPAIR_DEPTH."""
    def __init__(self, depth: int):
        super().__init__(f"Repair depth {depth} exceeds MAX_REPAIR_DEPTH={MAX_REPAIR_DEPTH}")


class RetryDepthExceeded(Exception):
    """Retry chain exceeded MAX_RETRY_DEPTH."""
    def __init__(self, depth: int):
        super().__init__(f"Retry depth {depth} exceeds MAX_RETRY_DEPTH={MAX_RETRY_DEPTH}")


# ===========================================================================
# Acceptance check
# ===========================================================================


def system_acceptance_check(report: IssueCollector,
                            mode: SystemMode = SystemMode.STRICT) -> bool:
    """Check the issue report against the configured mode.

    Returns True if the system is stable under the given mode.
    """
    if mode == SystemMode.DIAGNOSTIC:
        return True  # collect only, never fail

    b = StabilityBoundary

    if report.critical_count > b.MAX_CRITICAL_ISSUES:
        return False  # CRITICAL never allowed outside DIAGNOSTIC

    if mode == SystemMode.STRICT:
        if report.high_count > b.MAX_HIGH_ISSUES:
            return False
        if report.warning_count > b.MAX_ALLOWED_WARNINGS:
            return False

    return True


__all__ = [
    "StabilityBoundary",
    "SystemMode",
    "SYSTEM_MODE",
    "Severity",
    "IssueCategory",
    "IssueReport",
    "IssueCollector",
    "SystemUnstableError",
    "MAX_REPAIR_DEPTH",
    "MAX_RETRY_DEPTH",
    "RepairDepthExceeded",
    "RetryDepthExceeded",
    "system_acceptance_check",
]
