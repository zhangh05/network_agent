"""
SPEG Failure Semantics — explicit post-abort behavior definition.

Closes the semantic gap: every SystemUnstableError must have a
defined subsequent behavior (STOP / DEGRADE / RETRY_SESSION).
No silent crash, no undefined fallback, no None return.
"""

from __future__ import annotations

from typing import Any


class FailurePolicy:
    """Explicit post-abort behavior for each error type.

    Every entry MUST be one of: STOP, DEGRADE, RETRY_SESSION.
    Unmapped error types trigger a hard assertion at engine startup.
    """

    AFTER_ABORT_BEHAVIOR: dict[str, str] = {
        "SYSTEM_UNSTABLE_ERROR": "STOP",
    }

    @classmethod
    def behaviour_for(cls, error_type: str) -> str:
        """Return the defined behavior for an error type.

        Raises KeyError if the type is unmapped.
        """
        return cls.AFTER_ABORT_BEHAVIOR[error_type]


class FailureContext:
    """Carries the error, its stability report, and the recovery verdict.

    This object is the single source of truth for post-abort
    decision-making downstream.
    """

    __slots__ = ("error", "report", "recoverable")

    def __init__(self, error: Exception, report: Any):
        self.error = error
        self.report = report
        self.recoverable = self._is_recoverable()

    def _is_recoverable(self) -> bool:
        if self.report.critical_count > 0:
            return False
        if self.report.high_count > 0:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_type": type(self.error).__name__,
            "error_message": str(self.error),
            "recoverable": self.recoverable,
            "report": self.report.to_dict() if hasattr(self.report, "to_dict") else {},
        }


def degraded_result(failure_ctx: FailureContext) -> dict[str, Any]:
    """Explicit DEGRADED fallback — system continues in reduced mode."""
    return {
        "status": "DEGRADED",
        "reason": str(failure_ctx.error),
        "recoverable": failure_ctx.recoverable,
        "report": failure_ctx.report.to_dict() if hasattr(failure_ctx.report, "to_dict") else {},
    }


def retry_session_result(failure_ctx: FailureContext) -> dict[str, Any]:
    """Explicit RETRY_SCHEDULED fallback — caller should re-submit."""
    return {
        "status": "RETRY_SCHEDULED",
        "reason": str(failure_ctx.error),
        "retry_allowed": failure_ctx.recoverable,
        "report": failure_ctx.report.to_dict() if hasattr(failure_ctx.report, "to_dict") else {},
    }


__all__ = [
    "FailurePolicy",
    "FailureContext",
    "degraded_result",
    "retry_session_result",
]
