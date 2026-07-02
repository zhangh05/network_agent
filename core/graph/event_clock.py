"""
Global Event Clock — monotonic, globally ordered.

Rules:
  - ALL events MUST use EventClock.next()
  - NO local timestamp generation (time.time(), datetime.now(), etc.)
  - event.causal_index MUST be globally unique + monotonic
  - Thread-safe, process-safe (on same machine)

Architecture:
  EventClock.next(run_id) → (causal_index, timestamp)
    - causal_index: globally monotonic across all runs
    - timestamp: monotonic within this process
"""

from __future__ import annotations

import threading
import time as _time
from dataclasses import dataclass


@dataclass(frozen=True)
class EventStamp:
    """A globally-ordered timestamp + index pair."""
    causal_index: int         # globally unique + monotonic
    timestamp_iso: str        # ISO 8601, monotonic within process


class EventClock:
    """Global monotonic event clock.

    Singleton. Thread-safe. Guarantees causal ordering.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._global_index: int = 0
        self._last_ts: float = 0.0
        self._per_run: dict[str, int] = {}

    def next(self, run_id: str) -> EventStamp:
        """Get the next globally-ordered event stamp.

        Returns (causal_index, timestamp_iso) where:
        - causal_index is globally unique and monotonically increasing
        - timestamp is monotonically increasing within this process
        """
        import datetime

        with self._lock:
            self._global_index += 1
            idx = self._global_index
            run_local = self._per_run.get(run_id, 0) + 1
            self._per_run[run_id] = run_local

            # Ensure monotonic timestamp
            now = _time.time()
            if now <= self._last_ts:
                now = self._last_ts + 0.000001  # bump by 1μs
            self._last_ts = now

        ts = datetime.datetime.fromtimestamp(
            now, tz=datetime.timezone.utc
        ).isoformat()

        return EventStamp(causal_index=idx, timestamp_iso=ts)

    @property
    def global_index(self) -> int:
        with self._lock:
            return self._global_index

    @property
    def last_timestamp(self) -> str:
        import datetime
        with self._lock:
            ts = datetime.datetime.fromtimestamp(
                self._last_ts, tz=datetime.timezone.utc
            ).isoformat()
        return ts

    # ── Validation ───────────────────────────────────────────────

    def validate_monotonic(self, stamps: list[EventStamp]) -> bool:
        """Verify a sequence of stamps is monotonically increasing."""
        for i in range(1, len(stamps)):
            if stamps[i].causal_index <= stamps[i-1].causal_index:
                return False
            if stamps[i].timestamp_iso < stamps[i-1].timestamp_iso:
                return False
        return True


# ── Singleton ──────────────────────────────────────────────────────────

_clock: EventClock | None = None
_clock_lock = threading.Lock()


def get_event_clock() -> EventClock:
    global _clock
    if _clock is None:
        with _clock_lock:
            if _clock is None:
                _clock = EventClock()
    return _clock


def reset_event_clock() -> None:
    global _clock
    with _clock_lock:
        _clock = EventClock()
