# agent/runtime/utils/time_utils.py
"""Single source of truth for timestamp formatting.

All persisted/user-visible timestamps are timezone-aware ISO-8601 UTC strings.
Runtime arithmetic should convert through ``from_iso`` / ``duration_ms``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Union


def to_iso(ts: Union[float, str, None]) -> str:
    """Coerce a timestamp to ISO-8601 UTC string.

    ``None`` returns the current UTC time as ISO (treats unset as "now").
    ``str`` must already be a timezone-aware ISO timestamp.
    ``float`` is interpreted as Unix epoch seconds for internal callers.
    """
    if ts is None:
        return datetime.now(timezone.utc).isoformat()
    if isinstance(ts, str):
        from_iso(ts)
        return ts
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()


def from_iso(s: str) -> float:
    """Parse ISO-8601 string back to Unix epoch seconds (float)."""
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware ISO-8601")
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
