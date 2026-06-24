# agent/runtime/tool_execution/retry_policy.py
"""Retry policy helpers for tool execution.

v3.3: Exponential backoff + circuit breaker + smart retry orchestration.
"""

from __future__ import annotations

import json
import time
from typing import Any


# ─── Exponential Backoff ──────────────────────────────────────────────

def backoff_delay(attempt: int, base_ms: int = 500, max_ms: int = 10000) -> float:
    """Calculate exponential backoff delay: base * 2^(attempt-1), capped at max_ms."""
    delay = min(base_ms * (2 ** max(0, attempt - 1)), max_ms)
    return delay / 1000.0  # return in seconds


# ─── Circuit Breaker ───────────────────────────────────────────────────

class CircuitBreaker:
    """Track consecutive failures and break the circuit when threshold exceeded."""

    def __init__(self, failure_threshold: int = 3, reset_after_s: float = 30.0):
        self.failure_threshold = failure_threshold
        self.reset_after_s = reset_after_s
        self.failures: dict[str, list[float]] = {}  # tool_id -> [timestamps]
        self.open_circuits: dict[str, float] = {}   # tool_id -> opened_at

    def record_failure(self, tool_id: str) -> bool:
        """Record a failure for tool_id. Returns True if circuit opens."""
        now = time.time()
        self.failures.setdefault(tool_id, []).append(now)
        # Trim old failures outside the window
        self.failures[tool_id] = [
            ts for ts in self.failures[tool_id]
            if now - ts < self.reset_after_s
        ]
        if len(self.failures[tool_id]) >= self.failure_threshold:
            self.open_circuits[tool_id] = now
            return True
        return False

    def record_success(self, tool_id: str) -> None:
        """Reset circuit for tool_id on success."""
        self.failures.pop(tool_id, None)
        self.open_circuits.pop(tool_id, None)

    def is_open(self, tool_id: str) -> bool:
        """Check if circuit is open (tool should not be called)."""
        opened = self.open_circuits.get(tool_id)
        if not opened:
            return False
        if time.time() - opened > self.reset_after_s:
            # Auto-reset after cooldown
            self.open_circuits.pop(tool_id, None)
            self.failures.pop(tool_id, None)
            return False
        return True

    def reset_all(self) -> None:
        self.failures.clear()
        self.open_circuits.clear()


# ─── Global instance ───────────────────────────────────────────────────

_default_breaker = CircuitBreaker()


def get_circuit_breaker() -> CircuitBreaker:
    return _default_breaker


# ─── Repeated failure detection ────────────────────────────────────────


def detect_repeated_tool_failure(tool_results: list) -> dict | None:
    """Detect an identical failed tool result repeated back-to-back."""
    if len(tool_results) < 2:
        return None
    previous, current = tool_results[-2], tool_results[-1]
    if previous.get("ok") or current.get("ok"):
        return None
    if previous.get("tool_id") != current.get("tool_id"):
        return None
    previous_errors = tuple(previous.get("errors") or [])
    current_errors = tuple(current.get("errors") or [])
    if previous_errors != current_errors:
        return None
    if not current_errors and previous.get("summary") != current.get("summary"):
        return None
    return current


# ─── Smart retry decision ──────────────────────────────────────────────


def should_retry_tool(
    tool_id: str,
    attempts: int,
    error: str = "",
    max_retries: int = 3,
    breaker: CircuitBreaker | None = None,
) -> tuple[bool, float]:
    """Decide whether to retry a failed tool call.

    Returns (should_retry, delay_seconds).

    Logic:
    - Max retries: max_retries (default 3)
    - Exponential backoff between retries
    - Circuit breaker: if tool has N consecutive failures in window, stop
    - Non-retryable errors (auth, permission) bail immediately
    """
    b = breaker or _default_breaker

    if b.is_open(tool_id):
        return False, 0.0

    if attempts >= max_retries:
        b.record_failure(tool_id)
        return False, 0.0

    # Non-retryable errors
    non_retryable = [
        "authentication failed", "permission denied", "forbidden",
        "not found", "invalid argument", "not supported",
        "no such device", "host unreachable", "connection refused (max retries)",
    ]
    error_lower = (error or "").lower()
    for nr in non_retryable:
        if nr in error_lower:
            b.record_failure(tool_id)
            return False, 0.0

    delay = backoff_delay(attempts)
    return True, delay


def record_tool_success(tool_id: str, breaker: CircuitBreaker | None = None) -> None:
    b = breaker or _default_breaker
    b.record_success(tool_id)


def record_tool_failure(tool_id: str, breaker: CircuitBreaker | None = None) -> None:
    b = breaker or _default_breaker
    b.record_failure(tool_id)


# ─── Required tool retry ───────────────────────────────────────────────


def should_retry_for_required_tools(context, all_tool_results: list, step: int) -> bool:
    if step != 1 or all_tool_results:
        return False
    if getattr(context, "metadata", {}).get("required_tool_retry_used"):
        return False
    scene = (getattr(context, "safe_context", {}) or {}).get("tool_scene") or {}
    if not isinstance(scene, dict) or scene.get("needs_clarification"):
        return False
    required_steps = [
        s for s in scene.get("tool_plan", []) or []
        if isinstance(s, dict) and s.get("required") and s.get("tool_candidates")
    ]
    visible = set(getattr(context, "visible_tool_ids", []) or getattr(context, "metadata", {}).get("visible_tools", []) or [])
    if not required_steps or not visible:
        return False
    return any(set(step_def.get("tool_candidates") or []) & visible for step_def in required_steps)


def required_tool_retry_prompt(context) -> str:
    scene = (getattr(context, "safe_context", {}) or {}).get("tool_scene") or {}
    required = []
    if isinstance(scene, dict):
        for step_def in scene.get("tool_plan", []) or []:
            if isinstance(step_def, dict) and step_def.get("required"):
                required.append({
                    "step": step_def.get("step"),
                    "goal": step_def.get("goal"),
                    "tool_candidates": step_def.get("tool_candidates"),
                })
    return (
        "The current user request requires tool execution before a final answer. "
        "Do not answer from memory or general knowledge. Call one of the exposed "
        "functions for the first required step now. Required plan: "
        + json.dumps(required[:4], ensure_ascii=False)
    )


# ─── Turn-level retry orchestration ────────────────────────────────────


class TurnRetryPolicy:
    """Per-turn retry state machine.

    Tracks tool attempts within a turn, applies circuit breaker,
    and decides whether to continue or abort the current step.
    """

    def __init__(self, max_step_retries: int = 3):
        self.max_step_retries = max_step_retries
        self.breaker = _default_breaker
        self.attempts: dict[str, int] = {}       # tool_id -> attempt count this turn
        self.step_retries: int = 0

    def can_retry_step(self) -> bool:
        """Check if the current step can be retried."""
        return self.step_retries < self.max_step_retries

    def record_attempt(self, tool_id: str, success: bool, error: str = "") -> None:
        if success:
            self.attempts.pop(tool_id, None)
            self.breaker.record_success(tool_id)
            self.step_retries = 0
        else:
            self.attempts[tool_id] = self.attempts.get(tool_id, 0) + 1
            self.breaker.record_failure(tool_id)
            self.step_retries += 1

    def step_should_abort(self) -> tuple[bool, str]:
        """Check if step should be aborted. Returns (should_abort, reason)."""
        if self.step_retries >= self.max_step_retries:
            return True, f"max_step_retries ({self.max_step_retries}) exceeded"
        open_circuits = [
            tid for tid in self.breaker.open_circuits
            if self.breaker.is_open(tid)
        ]
        if open_circuits:
            return True, f"circuit_breaker_open: {', '.join(open_circuits[:3])}"
        return False, ""
