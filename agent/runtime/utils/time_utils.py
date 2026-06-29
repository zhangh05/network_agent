# agent/runtime/utils/time_utils.py
"""v3.9.8: Single source of truth for timestamp formatting.

Earlier versions split timestamps across two representations:
  - float (Unix epoch seconds)  — used by ApprovalRequest,
    agent.runtime.actions.models.ActionResult, agent.task.Task
  - str  (ISO 8601)              — used by everything else in the
    durable.* / state.* / event.* namespace

This led to a same-field, different-type split at the API boundary
(``created_at: float`` for approvals, ``created_at: str`` for
state/tokens/events). The 2024-06 audit surfaced it; v3.9.8 unifies
all *user-visible* timestamp fields to **str (ISO 8601, UTC)**.

For the rare case where back-end code needs to do arithmetic on a
timestamp string (``finished_at - started_at``), use ``from_iso``.
For the rare case where a legacy caller still has a float, accept
``float | str`` via ``to_iso``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Union


def to_iso(ts: Union[float, str, None]) -> str:
    """Coerce a timestamp to ISO-8601 UTC string.

    ``None`` returns the current UTC time as ISO (treats unset as "now").
    ``str`` is returned verbatim — assumed already ISO-formatted.
    ``float`` is interpreted as Unix epoch seconds (with optional
    millisecond precision).
    """
    if ts is None:
        return datetime.now(timezone.utc).isoformat()
    if isinstance(ts, str):
        return ts
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()


def from_iso(s: str) -> float:
    """Parse ISO-8601 string back to Unix epoch seconds (float)."""
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def now_iso() -> str:
    """ISO-8601 timestamp of the current UTC moment."""
    return datetime.now(timezone.utc).isoformat()


def duration_ms(started_at: str, finished_at: str) -> int:
    """Return the millisecond duration between two ISO-8601 timestamps.

    Rounded to the nearest integer (the canonical ToolResult /
    RuntimeStep.duration_ms shape is ``int``, not ``float``).
    """
    return int(round((from_iso(finished_at) - from_iso(started_at)) * 1000))
