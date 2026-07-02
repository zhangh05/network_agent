"""
Core data models for SSOT Runtime Engine.

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


class NodePriority(enum.Enum):
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class RiskLevel(enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


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
    priority: NodePriority = NodePriority.NORMAL
    optional: bool = False
    node_run_id: str = ""
    approval_required: bool = False
    approval_granted: bool = False
    # v3.10: action-alias normalization bookkeeping. The GraphCompiler
    # rewrites any alias (e.g. ``session_get``) into the canonical
    # ``action`` token, then records the original token + a flag on
    # the node so audit / risk / trace can surface what really
    # happened.
    action_original: str = ""
    action_normalized_from_alias: bool = False

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
    error_code: str = ""
    latency_ms: float = 0.0
    retry_count: int = 0
    # v3.10 (tool retry): per-node retry provenance. Written by
    # the execution engine when a retry actually fired, and
    # surfaced to audit / trace / SSOTRuntimeResult metadata.
    metadata: dict[str, Any] = field(default_factory=dict)
    # v4.1 (diagnostic preservation): raw error code from the tool
    # handler and the normalized code after the resolver. These
    # are always present so audit/retry/finalizer never lose error
    # provenance.
    error_code_raw: str = ""
    error_code_norm: str = ""


@dataclass
class SSOTRuntimeConfig:
    """Configuration for the SSOT Runtime Engine."""
    max_retries_per_node: int = 1
    parallel_layer_timeout_ms: int = 300_000
    single_node_timeout_ms: int = 120_000
    planner_timeout_ms: int = 20_000
    finalizer_timeout_ms: int = 15_000
    enable_finalizer: bool = True
    max_nodes: int = 30
    max_depth: int = 8
    max_global_concurrency: int = 8
    max_layer_concurrency: int = 5
    max_total_seconds: int = 60
    max_tool_seconds: int = 30
    max_llm_calls: int = 2

    # v3.12: RiskPolicy thresholds
    # Total tool nodes: <=20 → no approval trigger;
    #   >20 ≤50 → approval_required; >50 → hard_block.
    rp_max_tool_nodes_allow: int = 20
    rp_max_tool_nodes_approval: int = 50

    # Exec.run command count: ≤5 → no approval trigger;
    #   >5 ≤20 → approval_required; >20 → hard_block.
    rp_max_exec_allow: int = 5
    rp_max_exec_approval: int = 20


@dataclass
class SSOTRuntimeResult:
    """Final result from a SSOT Runtime Engine execution."""
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


# ============================================================================
# Bank-grade additions
# ============================================================================

@dataclass
class ExecutionBudget:
    """Per-request execution budget — enforced by BudgetController."""
    max_total_seconds: int = 60
    max_planner_seconds: int = 20
    max_tool_seconds: int = 30
    max_finalizer_seconds: int = 15
    max_nodes: int = 30
    max_depth: int = 8
    max_parallel_width: int = 8
    max_llm_calls: int = 2


@dataclass
class RollbackAction:
    """A rollback step for a mutation node."""
    node_id: str
    rollback_tool: str
    args: dict[str, Any] = field(default_factory=dict)
    reason: str = ""


@dataclass
class RollbackPlan:
    """Rollback assessment for the entire DAG run."""
    rollback_available: bool = False
    rollback_recommended: bool = False
    actions: list[RollbackAction] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class AuditRecord:
    """Immutable audit record for a single request."""
    request_id: str
    session_id: str
    created_at: float = field(default_factory=time.time)
    user_request_hash: str = ""
    planner_model: str = ""
    llm_call_count: int = 0
    dag_nodes: int = 0
    dag_depth: int = 0
    risk_level: str = "low"
    approval_required: bool = False
    executed_nodes: list[dict[str, Any]] = field(default_factory=list)
    blocked_nodes: list[dict[str, Any]] = field(default_factory=list)
    failed_nodes: list[dict[str, Any]] = field(default_factory=list)
    duration_ms: float = 0.0


@dataclass
class TraceSpan:
    """A single span in the execution trace."""
    name: str
    start_time: float
    end_time: float = 0.0
    duration_ms: float = 0.0
    status: str = "pending"
    error_code: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    children: list["TraceSpan"] = field(default_factory=list)


@dataclass
class MetricSnapshot:
    """Structured metrics for every run."""
    total_duration_ms: float = 0.0
    planner_duration_ms: float = 0.0
    compile_duration_ms: float = 0.0
    validation_duration_ms: float = 0.0
    execution_duration_ms: float = 0.0
    finalizer_duration_ms: float = 0.0
    llm_calls: int = 0
    tool_calls: int = 0
    tool_success: int = 0
    tool_failed: int = 0
    cache_hit_ratio: float = 0.0
    dag_depth: int = 0
    max_parallel_width: int = 0
    risk_level: str = "low"


# ============================================================================
# v3.14: Conversation Context
# ============================================================================

@dataclass
class ConversationContext:
    """Structured conversation context for injection into SSOT Runtime prompts.

    Replaces the naive ``messages[-10:]`` approach with:
      - Token-budgeted recent complete turns
      - Rolling session summary for older messages
      - Retrieved history for cross-turn reference resolution
      - Exact previous user/assistant message access
    """
    # Recent complete turns, truncated by token budget (≈chars for CJK).
    recent_messages: list[dict[str, str]] = field(default_factory=list)

    # Rolling summary of messages older than the recent window.
    session_summary: str = ""

    # Retrieved history entries (from message_store) when the user
    # makes a cross-turn reference (e.g. "前面提到的", "上一个任务").
    retrieved_history: list[dict[str, str]] = field(default_factory=list)

    # Last two messages in the session for exact reference.
    previous_user_message: str = ""
    previous_assistant_message: str = ""

    # Total approximate token count of recent_messages (characters / 1.5).
    token_estimate: int = 0

    @property
    def has_context(self) -> bool:
        return bool(self.recent_messages or self.session_summary)

    def format_for_prompt(self, max_summary_chars: int = 2000) -> str:
        """Format the full context into a prompt-ready block.

        Layout:
          1. SESSION SUMMARY (older turns)
          2. RECENT CONVERSATION HISTORY (complete recent turns)
          3. RETRIEVED HISTORY (cross-turn references)
        """
        parts: list[str] = []

        if self.session_summary:
            summary = self.session_summary[:max_summary_chars]
            parts.append(f"SESSION SUMMARY:\n{summary}")

        if self.recent_messages:
            lines = ["RECENT CONVERSATION HISTORY:"]
            for i, entry in enumerate(self.recent_messages, 1):
                role = entry.get("role", "unknown")
                content = entry.get("content", "")
                lines.append(f"  [{i}] {role}: {content}")
            parts.append("\n".join(lines))

        if self.retrieved_history:
            lines = ["RETRIEVED HISTORY (from earlier in session):"]
            for i, entry in enumerate(self.retrieved_history, 1):
                role = entry.get("role", "unknown")
                content = entry.get("content", "")
                lines.append(f"  [{i}] {role}: {content}")
            parts.append("\n".join(lines))

        return "\n\n".join(parts) if parts else ""
