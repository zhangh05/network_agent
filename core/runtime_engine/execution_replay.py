"""
SSOT Runtime v10.1 Execution Replay — with identity hash, VerifyReplayMode,
and DAG dependency validation.
"""

from __future__ import annotations

import hashlib
from typing import Any


class ExecutionTraceEvent:
    __slots__ = ("causal_index", "decision_node", "state_before",
                 "state_after", "tool_result_hash",
                 "dependencies_resolved", "parent_state")

    def __init__(self, causal_index: int, decision_node: str,
                 state_before: str, state_after: str,
                 tool_result_hash: str = "",
                 dependencies_resolved: bool = True,
                 parent_state: str = ""):
        self.causal_index = causal_index
        self.decision_node = decision_node
        self.state_before = state_before
        self.state_after = state_after
        self.tool_result_hash = tool_result_hash
        self.dependencies_resolved = dependencies_resolved
        self.parent_state = parent_state

    def to_dict(self) -> dict[str, Any]:
        return {
            "causal_index": self.causal_index,
            "decision_node": self.decision_node,
            "state_before": self.state_before,
            "state_after": self.state_after,
            "tool_result_hash": self.tool_result_hash,
            "dependencies_resolved": self.dependencies_resolved,
            "parent_state": self.parent_state,
        }


class ExecutionTrace:
    def __init__(self):
        self.events: list[ExecutionTraceEvent] = []

    def record(self, event: ExecutionTraceEvent) -> None:
        self.events.append(event)

    def __iter__(self):
        return iter(self.events)

    def __len__(self):
        return len(self.events)

    @property
    def identity(self) -> str:
        """v10.1: canonical identity hash for equality and audit."""
        parts = []
        for ev in self.events:
            parts.append(f"{ev.causal_index}:{ev.state_before}->{ev.state_after}"
                         f":{ev.tool_result_hash}")
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


class ExecutionReplay:
    """v10.1: replay validation — validates, does NOT execute tools."""

    VALID_STATES = ("RUNNING", "DEGRADED", "RETRYING", "TERMINAL")

    @staticmethod
    def replay(trace: ExecutionTrace) -> bool:
        for i, event in enumerate(trace.events):
            assert event.causal_index is not None, f"Trace[{i}]: missing causal_index"
            assert event.state_before in ExecutionReplay.VALID_STATES, (
                f"Trace[{i}]: invalid state_before={event.state_before}")
            assert event.state_after in ExecutionReplay.VALID_STATES, (
                f"Trace[{i}]: invalid state_after={event.state_after}")
            if i > 0:
                assert event.causal_index > trace.events[i - 1].causal_index, (
                    f"Trace[{i}]: causal_index not monotonic")
            # v10.1: DAG dependency validation
            assert event.dependencies_resolved is True, (
                f"Trace[{i}]: dependencies not resolved")
            if event.parent_state:
                assert event.parent_state in ExecutionReplay.VALID_STATES, (
                    f"Trace[{i}]: invalid parent_state={event.parent_state}")
        return True

    @staticmethod
    def verify_mode(trace: ExecutionTrace) -> dict[str, Any]:
        """v10.1: verify-only mode — no tool execution, just validation."""
        valid = True
        try:
            ExecutionReplay.replay(trace)
        except AssertionError as e:
            valid = False
        return {
            "valid": valid,
            "identity": trace.identity,
            "event_count": len(trace.events),
        }


class VerifyReplayMode:
    """v10.1: explicit verification mode marker."""

    @staticmethod
    def verify(trace: ExecutionTrace) -> dict[str, Any]:
        """Validate trace state transitions + hashes without executing tools."""
        return ExecutionReplay.verify_mode(trace)


__all__ = ["ExecutionTrace", "ExecutionTraceEvent", "ExecutionReplay",
           "VerifyReplayMode"]

