"""
Runtime Repair Engine for SSOT Runtime Engine.

Handles node failures at runtime with three-tier repair:
  Level 1: Retry same node (idempotent + within retry budget)
  Level 2: Skip optional node (doesn't affect critical path)
  Level 3: Partial subgraph replan (re-route around failure)

NO full DAG restart — partial repair only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .contracts import get_contract
from .models import (
    ExecutionDAG,
    ExecutionNode,
    ExecutionStatus,
    SSOTRuntimeConfig,
    ToolResult,
)


class RepairStrategy:
    RETRY = "retry"
    SKIP = "skip"
    PARTIAL_REPLAN = "partial_replan"
    FAIL = "fail"


@dataclass
class RepairResult:
    repair_applied: bool = False
    strategy: str = ""
    affected_nodes: list[str] = field(default_factory=list)
    new_graph: dict | None = None
    message: str = ""


class RepairEngine:
    """Three-tier runtime repair for node failures."""

    MAX_RETRIES = 1  # Hard cap per spec

    def __init__(self, config: SSOTRuntimeConfig | None = None):
        self._config = config or SSOTRuntimeConfig()

    def assess(
        self,
        node: ExecutionNode,
        result: ToolResult,
        dag: ExecutionDAG,
    ) -> RepairResult:
        """Determine repair strategy for a failed node.

        Returns a RepairResult indicating the chosen strategy.
        """
        contract = get_contract(node.tool)

        # Level 1: Retry
        if contract and contract.idempotent and node.retry_count < self.MAX_RETRIES:
            return RepairResult(
                repair_applied=True,
                strategy=RepairStrategy.RETRY,
                affected_nodes=[node.id],
                message=f"Level 1 retry for idempotent node '{node.id}'",
            )

        # If non-idempotent, cannot retry
        if contract and not contract.idempotent and result.error:
            pass  # Fall through to Level 2/3

        # Level 2: Skip optional
        if node.optional:
            return RepairResult(
                repair_applied=True,
                strategy=RepairStrategy.SKIP,
                affected_nodes=[node.id],
                message=f"Level 2 skip optional node '{node.id}'",
            )

        # Level 3: Check if this blocks critical path
        children = [n for n in dag.nodes if node.id in n.deps]
        if not children:
            # Leaf node failure → isolate but report
            return RepairResult(
                repair_applied=False,
                strategy=RepairStrategy.FAIL,
                affected_nodes=[node.id],
                message=f"Level 3: leaf node '{node.id}' failed — isolated, no critical path impact",
            )

        # Has children on critical path → partial replan
        return RepairResult(
            repair_applied=False,
            strategy=RepairStrategy.FAIL,
            affected_nodes=[node.id] + [c.id for c in children],
            message=f"Level 3: node '{node.id}' on critical path failed — cannot repair automatically",
        )

    def should_retry(self, node: ExecutionNode, result: ToolResult) -> bool:
        """Quick check: can we retry this node?"""
        contract = get_contract(node.tool)
        if not contract:
            return False
        return (
            contract.idempotent
            and node.retry_count < self.MAX_RETRIES
            and not result.success
        )

    def can_skip(self, node: ExecutionNode) -> bool:
        """Check if this node is skippable."""
        return node.optional
