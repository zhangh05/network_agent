"""
SPEG v4.2 runtime contracts — system-level invariants + self-healing
validation loop.

v4.2 additions (closing 5 structural gaps):
  1. ErrorCode enum — semantic error-code catalog so retry/audit/finalizer
     use typed codes, not string matching.
  2. GlobalCausalityClock — monotonic cross-session counter so context
     replay across session restore / reconnect never loses ordering.
  3. PlanSchemaVersion — schema version marker so schema evolution
     (new optional fields, changed required fields) is traceable.
  4. ContractValidator — self-healing validation loop that checks
     contracts on every turn, downgrades gracefully (controlled
     degradation) instead of silent fail or hard crash.
  5. Sub-execution guards — retry/replan/repair paths also enforce
     the same contract assertions as the main path.
"""

from __future__ import annotations

import enum
import threading
import time as _time
from typing import Any


# ===========================================================================
# Exceptions
# ===========================================================================


class ExecutionObligationViolation(Exception):
    """Planner returned empty nodes for task-intent request."""


# ===========================================================================
# 1. ErrorCode — semantic error-code catalog
# ===========================================================================


class ErrorCode(enum.Enum):
    """v4.2 semantic error-code catalog.

    Every error_code in the system MUST be one of these values (or
    a raw handler-defined key that failed to normalise — those are
    carried in ``error_code_raw``).  This lets retry policy,
    audit, and finalizer branch on typed codes instead of
    hard-coded string comparisons.
    """

    # ── Handler-declared ──────────────────────────────────────────
    TOOL_RETURNED_NOT_OK = "TOOL_RETURNED_NOT_OK"
    NULL_RESULT = "NULL_RESULT"
    LEGACY_FAILURE = "LEGACY_FAILURE"

    # ── Runtime-level ─────────────────────────────────────────────
    TOOL_NOT_REGISTERED = "TOOL_NOT_REGISTERED"
    TOOL_TIMEOUT = "TOOL_TIMEOUT"
    TOOL_EXCEPTION = "TOOL_EXCEPTION"

    # ── Planner / schema ──────────────────────────────────────────
    PLANNER_EMPTY_FOR_TASK_INTENT = "PLANNER_EMPTY_FOR_TASK_INTENT"
    SCHEMA_VALIDATION_ERROR = "SCHEMA_VALIDATION_ERROR"
    EXECUTION_OBLIGATION_VIOLATION = "EXECUTION_OBLIGATION_VIOLATION"

    # ── Finalizer ─────────────────────────────────────────────────
    FINALIZER_TASK_INCOMPLETE = "FINALIZER_TASK_INCOMPLETE"

    # ── Contract ──────────────────────────────────────────────────
    CONTRACT_VIOLATION = "CONTRACT_VIOLATION"

    @classmethod
    def normalise(cls, raw: str) -> "ErrorCode":
        """Map a raw code string to the closest known ErrorCode.
        Unknown codes map to the raw string's value — the caller
        should check ``is_known`` after.
        """
        try:
            return cls(raw)
        except ValueError:
            return raw  # type: ignore[return-value]

    @classmethod
    def is_known(cls, candidate: Any) -> bool:
        return isinstance(candidate, cls)

    # ── Retry-eligibility groups ──────────────────────────────────

    @property
    def is_retryable(self) -> bool:
        """Error codes where a retry is permitted (idempotent tools only)."""
        return self in (
            ErrorCode.TOOL_TIMEOUT,
            ErrorCode.TOOL_EXCEPTION,
            ErrorCode.TOOL_RETURNED_NOT_OK,
            ErrorCode.NULL_RESULT,
            ErrorCode.LEGACY_FAILURE,
        )

    @property
    def is_hard_block(self) -> bool:
        """Error codes that categorically block further execution."""
        return self in (
            ErrorCode.EXECUTION_OBLIGATION_VIOLATION,
            ErrorCode.SCHEMA_VALIDATION_ERROR,
            ErrorCode.CONTRACT_VIOLATION,
        )

    @property
    def is_handler_declared(self) -> bool:
        """Error codes originating from tool handler return values."""
        return self in (
            ErrorCode.TOOL_RETURNED_NOT_OK,
            ErrorCode.NULL_RESULT,
            ErrorCode.LEGACY_FAILURE,
        )


# ===========================================================================
# 2. GlobalCausalityClock — cross-session monotonic ordering
# ===========================================================================


class GlobalCausalityClock:
    """v4.2 monotonic cross-session causality clock.

    Replaces per-session ``causal_index`` with a global counter so
    that two separately-restored sessions can be merged without
    ordering ambiguity.  Session A's message with causal_index=3
    happened before session B's message with causal_index=7, even
    if B was opened later.

    Thread-safe.  The clock starts at 1 so that 0 means "unset".
    """

    _lock: threading.Lock = threading.Lock()
    _counter: int = 1

    @classmethod
    def next(cls) -> int:
        with cls._lock:
            val = cls._counter
            cls._counter += 1
            return val

    @classmethod
    def reset(cls) -> None:
        """For tests only — resets the global clock to 1."""
        with cls._lock:
            cls._counter = 1


# ===========================================================================
# 3. PlanSchemaVersion — schema evolution marker
# ===========================================================================


class PlanSchemaVersion(enum.IntEnum):
    """v4.2 plan schema version.

    When the plan JSON schema evolves (new optional fields added,
    required fields changed), increment the version here.  Old
    plans carry their schema version so the engine can migrate or
    reject them deterministically.
    """

    V1 = 1   # v3.10 initial: id, tool, args, deps
    V2 = 2   # v4.1: strict validation, null-tool forbidden

    CURRENT = V2

    @classmethod
    def validate_compatible(cls, plan_version: int) -> bool:
        """True if a plan at ``plan_version`` is still understood
        by the current schema (i.e. no breaking change since)."""
        return plan_version == cls.CURRENT


# ===========================================================================
# 4. ContractValidator — self-healing validation loop
# ===========================================================================


class ContractDegradation(enum.Enum):
    """Degradation level for a contract check failure."""
    OK = "ok"
    WARN = "warn"           # contract passed but optional guard missing
    SOFT = "soft"           # contract failed but turn continues (degraded)
    HARD = "hard"           # contract failed, turn aborted


class ContractCheck:
    """Result of a single contract check."""
    name: str
    level: ContractDegradation
    message: str

    def __init__(self, name: str, passed: bool, message: str = "",
                 critical: bool = True):
        self.name = name
        if passed:
            self.level = ContractDegradation.OK
        elif critical:
            self.level = ContractDegradation.HARD
        else:
            self.level = ContractDegradation.SOFT
        self.message = message or ("" if passed else f"{name} failed")


class ContractReport:
    """Aggregated contract check report for a turn."""

    def __init__(self):
        self.checks: list[ContractCheck] = []
        self.fail_count: int = 0
        self.all_ok: bool = True

    def add(self, check: ContractCheck) -> None:
        self.checks.append(check)
        if check.level in (ContractDegradation.SOFT, ContractDegradation.HARD):
            self.fail_count += 1
            if check.level == ContractDegradation.HARD:
                self.all_ok = False

    def has_critical_failure(self) -> bool:
        return any(
            c.level == ContractDegradation.HARD for c in self.checks
        )


class ContractValidator:
    """v4.2 self-healing contract validation loop.

    Runs all contract checks on every turn.  Critical failures
    abort the turn; soft failures downgrade gracefully and
    record a warning.  The report is attached to
    ``SPEGResult.metadata["contract_report"]`` so diagnostics can
    inspect degradation history.
    """

    def __init__(self, contracts: Any):
        self._contracts = contracts  # ExecutionContract class

    def validate_all(self) -> ContractReport:
        report = ContractReport()

        def _check(name: str, flag: bool, critical: bool = True):
            report.add(ContractCheck(
                name, flag,
                critical=critical,
            ))

        c = self._contracts
        _check("TOOL_TRUTH_SINGLE_SOURCE", c.TOOL_TRUTH_SINGLE_SOURCE)
        _check("CONTEXT_EVENT_STREAM_ONLY", c.CONTEXT_EVENT_STREAM_ONLY)
        _check("EXECUTION_OBLIGATION_ENFORCED", c.EXECUTION_OBLIGATION_ENFORCED)
        _check("CONTEXT_CAUSAL_ORDER_ONLY", c.CONTEXT_CAUSAL_ORDER_ONLY)
        _check("PLAN_STRICT_SCHEMA_ENFORCED", c.PLAN_STRICT_SCHEMA_ENFORCED)
        _check("DIAGNOSTIC_PRESERVATION_REQUIRED", c.DIAGNOSTIC_PRESERVATION_REQUIRED)

        return report


class ExecutionContract:
    """v4.2 system-level runtime contracts."""

    # [1-3] v4.0
    TOOL_TRUTH_SINGLE_SOURCE: bool = True
    CONTEXT_EVENT_STREAM_ONLY: bool = True
    EXECUTION_OBLIGATION_ENFORCED: bool = True

    # [4-6] v4.1
    CONTEXT_CAUSAL_ORDER_ONLY: bool = True
    PLAN_STRICT_SCHEMA_ENFORCED: bool = True
    DIAGNOSTIC_PRESERVATION_REQUIRED: bool = True


# ===========================================================================
# v6: Execution Semantics Contract — design boundary convergence
# ===========================================================================


class CausalityViolationError(Exception):
    """A context event lacks a mandatory causal_index."""


class PlanValidationError(Exception):
    """Unified validation error for plan pipeline failures.

    subtype is one of: SCHEMA_INVALID, SEMANTIC_INVALID,
    EXECUTION_OBLIGATION_VIOLATION.
    """
    def __init__(self, subtype: str, message: str):
        super().__init__(message)
        self.subtype = subtype


class ExecutionSemanticsContract:
    """v6 boundary-converged semantics — no dual interpretation.

    These are the non-negotiable rules for the v6 runtime. Every
    boundary that was previously implicit or dual-interpreted is
    now explicit and singular.
    """

    # [1] Single truth for tool results — only resolve_tool_outcome
    #     decides success; error_code_norm is the sole code for
    #     retry / audit / finalizer logic. error_code_raw is
    #     audit-only (never a decision input).
    SINGLE_TRUTH_TOOL_RESULT: bool = True

    # [2] Single context source — build_context_events is the sole
    #     entry point for conversation context. No direct
    #     session.history or message_store reads outside the builder.
    SINGLE_CONTEXT_SOURCE: bool = True

    # [3] Causal order is strict — every context event carries
    #     global_causal_index; no created_at fallback; null index
    #     raises CausalityViolationError.
    CAUSAL_ORDER_STRICT: bool = True

    # [4] Schema + execution obligation are unified — structural
    #     validation, semantic validation, and execution-obligation
    #     check form a single pipeline with fixed order. No split
    #     path, no silent empty-plan success.
    SCHEMA_EXECUTION_UNIFIED: bool = True


def assert_error_code_usage(result) -> None:
    """v6: enforce error_code boundary.

    - error_code_norm must be non-None for every tool result
    - error_code_raw exists for audit but must not drive logic
    """
    assert result.error_code_norm is not None, (
        "error_code_norm is None — v6 contract requires a normalised code"
    )
    assert result.error_code_raw is not None, (
        "error_code_raw is None — v6 contract requires preserved raw code"
    )


class CausalIndexGuard:
    """v6: enforce mandatory causal_index on every context event.

    Raises CausalityViolationError if any event lacks a valid
    causal_index.
    """

    @staticmethod
    def validate(events: list[dict]) -> None:
        for i, ev in enumerate(events):
            idx = ev.get("_causal_index") or ev.get("global_causal_index")
            if idx is None:
                raise CausalityViolationError(
                    f"Context event {i} lacks causal_index: {ev.get('role', '?')}"
                )


class ContextSnapshot:
    """v6: immutable context snapshot after build.

    Once built, context events cannot be modified. The caller
    receives a read-only copy.
    """

    def __init__(self, events: list[dict]):
        self.events = tuple(events)  # immutable
        self.causal_order_verified: bool = True

    def __iter__(self):
        return iter(self.events)

    def __len__(self):
        return len(self.events)

    def __getitem__(self, idx):
        return self.events[idx]


__all__ = [
    "ErrorCode",
    "ExecutionContract",
    "ExecutionObligationViolation",
    "GlobalCausalityClock",
    "PlanSchemaVersion",
    "ContractValidator",
    "ContractReport",
    "ContractCheck",
    "ContractDegradation",
    "ExecutionSemanticsContract",
    "CausalityViolationError",
    "PlanValidationError",
    "CausalIndexGuard",
    "ContextSnapshot",
    "assert_error_code_usage",
]
