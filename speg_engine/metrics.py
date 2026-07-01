"""
Metrics System for SPEG Engine.

Every run must emit structured metrics:
  - Timing breakdown (planner, compile, validation, execution, finalizer)
  - LLM call count (hard limit: 2)
  - Tool call count (success/failure)
  - DAG topology stats (depth, width)
  - Risk level

Used for observability and latency benchmarking.
"""

from __future__ import annotations

import time
from typing import Any

from .models import (
    ExecutionDAG,
    ExecutionNode,
    ExecutionStatus,
    MetricSnapshot,
    SPEGConfig,
    StatelessContext,
    ToolResult,
)


class MetricsCollector:
    """Collects and emits structured metrics per run."""

    def __init__(self):
        self._snapshot = MetricSnapshot()

    def capture_planner(self, duration_ms: float) -> None:
        self._snapshot.planner_duration_ms = duration_ms

    def capture_compile(self, duration_ms: float) -> None:
        self._snapshot.compile_duration_ms = duration_ms

    def capture_validation(self, duration_ms: float) -> None:
        self._snapshot.validation_duration_ms = duration_ms

    def capture_execution(
        self,
        duration_ms: float,
        node_results: dict[str, ToolResult],
        dag: ExecutionDAG,
    ) -> None:
        self._snapshot.execution_duration_ms = duration_ms
        self._snapshot.tool_calls = len(node_results)
        self._snapshot.tool_success = sum(1 for r in node_results.values() if r.success)
        self._snapshot.tool_failed = sum(1 for r in node_results.values() if not r.success)
        self._snapshot.dag_depth = dag.max_depth
        self._snapshot.max_parallel_width = max(
            (len(layer) for layer in dag.layers.values()), default=0
        )

    def capture_finalizer(self, duration_ms: float) -> None:
        self._snapshot.finalizer_duration_ms = duration_ms

    def capture_total(self, duration_ms: float) -> None:
        self._snapshot.total_duration_ms = duration_ms

    def set_llm_calls(self, count: int) -> None:
        self._snapshot.llm_calls = count

    def set_risk_level(self, level: str) -> None:
        self._snapshot.risk_level = level

    def snapshot(self) -> MetricSnapshot:
        return self._snapshot

    def to_dict(self) -> dict[str, Any]:
        s = self._snapshot
        return {
            "total_duration_ms": s.total_duration_ms,
            "planner_duration_ms": s.planner_duration_ms,
            "compile_duration_ms": s.compile_duration_ms,
            "validation_duration_ms": s.validation_duration_ms,
            "execution_duration_ms": s.execution_duration_ms,
            "finalizer_duration_ms": s.finalizer_duration_ms,
            "llm_calls": s.llm_calls,
            "tool_calls": s.tool_calls,
            "tool_success": s.tool_success,
            "tool_failed": s.tool_failed,
            "cache_hit_ratio": s.cache_hit_ratio,
            "dag_depth": s.dag_depth,
            "max_parallel_width": s.max_parallel_width,
            "risk_level": s.risk_level,
        }
