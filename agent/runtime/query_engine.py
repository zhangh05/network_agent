# agent/runtime/query_engine.py
"""Query Engine — error classification, retry policies, and trace generation.

Provides structured error types, LLM retry with exponential backoff,
and trace ID generation for turn-level observability.
"""

import time
import uuid
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Callable, Optional


# ═══════════════════════════
# Error classification
# ═══════════════════════════

class ErrorType:
    """Standard error type constants for structured error handling."""
    USER_INPUT_ERROR = "user_input_error"
    PERMISSION_DENIED = "permission_denied"
    APPROVAL_REQUIRED = "approval_required"
    TOOL_ERROR = "tool_error"
    MODEL_ERROR = "model_error"
    TOKEN_LIMIT = "token_limit"
    RATE_LIMIT = "rate_limit"
    INTERNAL_ERROR = "internal_error"


def classify_error(e: Exception) -> str:
    """Classify an exception into an ErrorType string.

    Args:
        e: The exception to classify.

    Returns:
        One of the ErrorType constants.
    """
    msg = str(e).lower()
    etype = type(e).__name__.lower()

    # Permission / approval
    if "permission" in msg or "denied" in msg or "forbidden" in msg:
        return ErrorType.PERMISSION_DENIED
    if "approval" in msg or "requires_approval" in msg:
        return ErrorType.APPROVAL_REQUIRED

    # Model / provider errors
    if "timeout" in msg or "timed out" in msg:
        if "provider" in msg or "model" in msg or "llm" in msg:
            return ErrorType.RATE_LIMIT
        return ErrorType.TOOL_ERROR
    if "rate" in msg and ("limit" in msg or "exceeded" in msg or "throttle" in msg):
        return ErrorType.RATE_LIMIT
    if "overloaded" in msg or "capacity" in msg:
        return ErrorType.RATE_LIMIT
    if "token" in msg and ("limit" in msg or "exceeded" in msg or "context" in msg or "length" in msg or "too long" in msg):
        return ErrorType.TOKEN_LIMIT
    if "model" in msg or "provider" in msg or "api" in msg:
        return ErrorType.MODEL_ERROR

    # Tool-related
    if "tool" in etype or "tool" in msg:
        return ErrorType.TOOL_ERROR

    # User input validation
    if "invalid" in msg or "validation" in msg or "required" in msg:
        if "argument" in msg or "param" in msg or "input" in msg or "field" in msg:
            return ErrorType.USER_INPUT_ERROR

    return ErrorType.INTERNAL_ERROR


# ═══════════════════════════
# Query result
# ═══════════════════════════

@dataclass
class QueryResult:
    """Structured result from a query execution."""
    ok: bool = False
    status: str = "unknown"
    error_type: str = ""
    final_response: str = ""
    tool_calls: list = field(default_factory=list)
    trace_id: str = ""
    session_id: str = ""
    turn_id: str = ""
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "status": self.status,
            "error_type": self.error_type,
            "final_response": self.final_response,
            "tool_calls": self.tool_calls,
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "metadata": self.metadata,
        }

    @staticmethod
    def success(trace_id: str = "", session_id: str = "", turn_id: str = "",
                final_response: str = "", tool_calls: list = None,
                metadata: dict = None) -> "QueryResult":
        return QueryResult(
            ok=True,
            status="succeeded",
            trace_id=trace_id,
            session_id=session_id,
            turn_id=turn_id,
            final_response=final_response,
            tool_calls=tool_calls or [],
            metadata=metadata or {},
        )

    @staticmethod
    def error(error_type: str, message: str = "", trace_id: str = "",
              session_id: str = "", turn_id: str = "",
              metadata: dict = None) -> "QueryResult":
        return QueryResult(
            ok=False,
            status="failed",
            error_type=error_type,
            final_response=message,
            trace_id=trace_id,
            session_id=session_id,
            turn_id=turn_id,
            metadata=metadata or {},
        )


# ═══════════════════════════
# LLM retry policy
# ═══════════════════════════

@dataclass
class LLMRetryPolicy:
    """Configuration for LLM call retry behaviour."""
    max_retries: int = 3
    backoff_base: float = 2.0
    retryable_errors: set = field(default_factory=lambda: {
        "provider_timeout",
        "rate_limit",
        "model_overloaded",
    })

    def is_retryable(self, error_type: str) -> bool:
        """Check whether an error type is eligible for retry."""
        return error_type in self.retryable_errors


DEFAULT_RETRY_POLICY = LLMRetryPolicy()


def with_retry(
    fn: Callable,
    policy: Optional[LLMRetryPolicy] = None,
    **kwargs,
) -> Callable:
    """Wrap a function with LLM retry policy (exponential backoff).

    Usage::

        @with_retry(invoke_llm, policy=LLMRetryPolicy(max_retries=3))
        def call_llm(messages, **opts):
            return invoke_llm(messages, **opts)

    Args:
        fn: The function to wrap with retry logic.
        policy: Retry policy. Uses DEFAULT_RETRY_POLICY if not provided.
        **kwargs: Additional keyword args passed to fn on each attempt.

    Returns:
        Wrapped callable that retries on retryable errors.
    """
    _policy = policy or DEFAULT_RETRY_POLICY

    @wraps(fn)
    def wrapper(*args, **fn_kwargs):
        last_error = None
        all_kwargs = {**kwargs, **fn_kwargs}

        for attempt in range(_policy.max_retries + 1):
            try:
                return fn(*args, **all_kwargs)
            except Exception as e:
                last_error = e
                error_type = classify_error(e)

                if not _policy.is_retryable(error_type) or attempt >= _policy.max_retries:
                    raise

                wait = _policy.backoff_base ** attempt
                time.sleep(wait)

        if last_error:
            raise last_error

    return wrapper


# ═══════════════════════════
# Trace ID generation
# ═══════════════════════════

def build_trace_id() -> str:
    """Generate a unique trace ID for a turn.

    Returns:
        UUID4 string suitable for correlating logs, audit events,
        and tool calls within a single turn.
    """
    return str(uuid.uuid4())
