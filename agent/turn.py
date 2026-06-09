# agent/turn.py
"""Turn lifecycle — inspired by Codex's agentic turn model.

A Turn is one agentic cycle within a Task. Each turn:
1. Model receives (history + context + tools)
2. Model decides: generate text or call tools
3. If tools called → execute → feed results back → next turn
4. If text generated → turn complete → task done

This is a lightweight tracker. The actual execution logic remains
in llm_orchestrator.py and skill_executor.py.
"""

from __future__ import annotations

import time
from typing import Any


class Turn:
    """Tracks one agentic execution cycle within a Task.

    A Turn is the atomic unit of agent-tool interaction:
    - The model receives state and decides what to do
    - Tools may be called (zero or more)
    - The model produces a final response (or defers)

    Each Turn carries metadata about what happened during that cycle,
    enabling observability and traceability.
    """

    __slots__ = (
        "turn_number", "started_at", "completed_at",
        "status", "tool_calls", "model_response",
        "error", "metadata",
    )

    def __init__(self, turn_number: int) -> None:
        self.turn_number: int = turn_number
        self.started_at: float = time.time()
        self.completed_at: float | None = None
        self.status: str = "pending"
        self.tool_calls: list[dict] = []       # [{tool_id, arguments, result}]
        self.model_response: str = ""
        self.error: str | None = None
        self.metadata: dict[str, Any] = {}

    def record_tool_call(self, tool_id: str, arguments: dict, result: dict | None = None) -> None:
        """Record a tool call within this turn."""
        self.tool_calls.append({
            "tool_id": tool_id,
            "arguments": arguments,
            "result": result,
        })

    def complete(self, model_response: str = "", metadata: dict | None = None) -> None:
        """Mark this turn as completed."""
        self.status = "completed"
        self.completed_at = time.time()
        self.model_response = model_response
        if metadata:
            self.metadata.update(metadata)

    def fail(self, error: str) -> None:
        """Mark this turn as failed."""
        self.status = "failed"
        self.completed_at = time.time()
        self.error = error

    @property
    def elapsed_ms(self) -> float:
        t1 = self.completed_at or time.time()
        return (t1 - self.started_at) * 1000

    @property
    def tool_count(self) -> int:
        return len(self.tool_calls)

    def as_dict(self) -> dict:
        return {
            "turn_number": self.turn_number,
            "status": self.status,
            "elapsed_ms": round(self.elapsed_ms, 2),
            "tool_count": self.tool_count,
            "tool_calls": [
                {"tool_id": tc["tool_id"], "ok": tc.get("result", {}).get("ok")}
                for tc in self.tool_calls
            ],
            "model_response_length": len(self.model_response),
            "error": self.error,
        }
