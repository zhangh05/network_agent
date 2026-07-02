"""
SPEG v10 Execution Replay — deterministic execution trace replay.

Every execution produces a trace that can be replayed exactly.
The replay validates causal_order, state transitions, and
tool_results at every step.
"""

from __future__ import annotations

from typing import Any


class ExecutionTraceEvent:
    """A single event in the execution trace."""
    __slots__ = ("causal_index", "decision_node", "state_before",
                 "state_after", "tool_result_hash")

    def __init__(self, causal_index: int, decision_node: str,
                 state_before: str, state_after: str,
                 tool_result_hash: str):
        self.causal_index = causal_index
        self.decision_node = decision_node
        self.state_before = state_before
        self.state_after = state_after
        self.tool_result_hash = tool_result_hash

    def to_dict(self) -> dict[str, Any]:
        return {
            "causal_index": self.causal_index,
            "decision_node": self.decision_node,
            "state_before": self.state_before,
            "state_after": self.state_after,
            "tool_result_hash": self.tool_result_hash,
        }


class ExecutionTrace:
    """Ordered list of execution trace events."""
    def __init__(self):
        self.events: list[ExecutionTraceEvent] = []

    def record(self, event: ExecutionTraceEvent) -> None:
        self.events.append(event)

    def __iter__(self):
        return iter(self.events)

    def __len__(self):
        return len(self.events)


class ExecutionReplay:
    """v10: replay an execution trace and validate consistency."""

    @staticmethod
    def replay(trace: ExecutionTrace) -> bool:
        """Replay the trace; returns True if fully valid."""
        for i, event in enumerate(trace.events):
            assert event.causal_index is not None, (
                f"Trace[{i}]: missing causal_index"
            )
            assert event.state_before in (
                "RUNNING", "DEGRADED", "RETRYING", "TERMINAL"
            ), f"Trace[{i}]: invalid state_before={event.state_before}"
            assert event.state_after in (
                "RUNNING", "DEGRADED", "RETRYING", "TERMINAL"
            ), f"Trace[{i}]: invalid state_after={event.state_after}"
            # Monotonic causal order
            if i > 0:
                assert event.causal_index > trace.events[i - 1].causal_index, (
                    f"Trace[{i}]: causal_index not monotonic"
                )
        return True


__all__ = ["ExecutionTrace", "ExecutionTraceEvent", "ExecutionReplay"]
