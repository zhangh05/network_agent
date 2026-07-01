"""
Core data models for SPEG Engine.

These define the Execution DAG IR and all runtime types.
No business logic — pure dataclasses and enums.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field
from typing import Any


class ExecutionStatus(enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    RETRYING = "retrying"


class DAGStatus(enum.Enum):
    """Validation status of the entire DAG."""
    VALID = "valid"
    INVALID_TOOL = "invalid_tool"
    INVALID_ARGS = "invalid_args"
    INVALID_DEPS = "invalid_deps"
    CYCLIC = "cyclic"
    UNSAFE_PATH = "unsafe_path"


@dataclass
class PlanNode:
    """A single node from the Planner LLM output."""
    id: str
    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    deps: list[str] = field(default_factory=list)


@dataclass
class ExecutionNode:
    """A compiled, validated DAG node ready for execution."""
    id: str
    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    deps: list[str] = field(default_factory=list)
    depth: int = 0
    status: ExecutionStatus = ExecutionStatus.PENDING
    result: Any | None = None
    error: str | None = None
    retry_count: int = 0
    started_at: float | None = None
    finished_at: float | None = None
    latency_ms: float = 0.0

    @property
    def is_ready(self) -> bool:
        return self.status == ExecutionStatus.PENDING

    @property
    def is_done(self) -> bool:
        return self.status in (
            ExecutionStatus.SUCCESS,
            ExecutionStatus.FAILED,
            ExecutionStatus.SKIPPED,
        )


@dataclass
class ExecutionDAG:
    """The compiled and validated execution DAG."""
    nodes: list[ExecutionNode]
    layers: dict[int, list[ExecutionNode]] = field(default_factory=dict)
    total_nodes: int = 0
    max_depth: int = 0
    status: DAGStatus = DAGStatus.VALID
    validation_errors: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return self.status == DAGStatus.VALID and not self.validation_errors

    def get_layer(self, depth: int) -> list[ExecutionNode]:
        return self.layers.get(depth, [])


@dataclass
class StatelessContext:
    """Minimal stateless context — a flat snapshot.

    No pipeline, no multi-stage rebuild, no precomputed evidence.
    Lazy injection per-node on demand.
    """
    workspace_id: str
    session_id: str
    request_id: str
    user_input: str
    cwd: str = ""
    os: str = ""
    timestamp: float = field(default_factory=time.time)
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResult:
    """Standardized result from any tool execution."""
    node_id: str
    tool: str
    success: bool
    data: Any = None
    error: str | None = None
    latency_ms: float = 0.0
    retry_count: int = 0


@dataclass
class SPEGConfig:
    """Configuration for the SPEG Engine."""
    max_retries_per_node: int = 1
    parallel_layer_timeout_ms: int = 300_000   # 5 min per layer
    single_node_timeout_ms: int = 120_000       # 2 min per node
    planner_timeout_ms: int = 60_000             # 1 min for planner LLM
    finalizer_timeout_ms: int = 30_000           # 30s for finalizer
    enable_finalizer: bool = True
    max_nodes: int = 32
    max_depth: int = 8


@dataclass
class SPEGResult:
    """Final result from a SPEG Engine execution."""
    request_id: str
    success: bool
    total_latency_ms: float = 0.0
    planner_latency_ms: float = 0.0
    execution_latency_ms: float = 0.0
    merge_latency_ms: float = 0.0
    finalizer_latency_ms: float = 0.0
    max_layer_latency_ms: float = 0.0
    node_results: dict[str, ToolResult] = field(default_factory=dict)
    final_response: str = ""
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def node_success_count(self) -> int:
        return sum(1 for r in self.node_results.values() if r.success)

    @property
    def node_failure_count(self) -> int:
        return sum(1 for r in self.node_results.values() if not r.success)
