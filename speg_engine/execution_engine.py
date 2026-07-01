"""
Async Execution Engine — the core parallel runtime of SPEG.

Executes a validated DAG layer by layer:
  layer_0 → parallel execution of all nodes
  layer_1 → parallel execution of all nodes
  ...
  layer_N

Each layer runs ALL nodes concurrently via asyncio.gather.
Nodes only execute once all their dependencies (previous layers) are done.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from .models import (
    ExecutionDAG,
    ExecutionNode,
    ExecutionStatus,
    SPEGConfig,
    SPEGResult,
    StatelessContext,
    ToolResult,
)
from .tool_runtime import ToolRuntime


class ExecutionEngine:
    """Async parallel DAG execution engine.

    Executes the DAG depth-first: all nodes at depth 0 run in parallel,
    then depth 1, etc. Each layer uses asyncio.gather for full parallelism.
    """

    MAX_RETRIES = 1  # Hard limit per spec

    def __init__(self, config: SPEGConfig, tool_runtime: ToolRuntime):
        self._config = config
        self._runtime = tool_runtime

    async def execute(
        self,
        dag: ExecutionDAG,
        ctx: StatelessContext,
    ) -> dict[str, ToolResult]:
        """Execute the full DAG asynchronously.

        Returns:
            Dict mapping node_id → ToolResult for all nodes.
        """
        start = time.monotonic()
        all_results: dict[str, ToolResult] = {}

        for depth in range(dag.max_depth + 1):
            layer_nodes = dag.get_layer(depth)
            if not layer_nodes:
                continue

            # Mark all nodes as running
            for node in layer_nodes:
                node.status = ExecutionStatus.RUNNING
                node.started_at = time.monotonic()

            # Execute all nodes in this layer in parallel
            layer_results = await self._runtime.execute_layer(
                layer_nodes, ctx, all_results
            )

            # Process results: handle failures with retry + isolation
            for node in layer_nodes:
                result = layer_results.get(node.id)
                if result is None:
                    result = ToolResult(
                        node_id=node.id,
                        tool=node.tool,
                        success=False,
                        error="No result returned from execution",
                    )

                if not result.success:
                    result = await self._handle_failure(node, ctx, all_results, layer_results)

                # Update node state
                node.result = result.data
                node.error = result.error
                node.status = ExecutionStatus.SUCCESS if result.success else ExecutionStatus.FAILED
                node.latency_ms = result.latency_ms
                node.finished_at = time.monotonic()
                all_results[node.id] = result

        execution_latency = (time.monotonic() - start) * 1000
        ctx.extras["execution_latency_ms"] = execution_latency

        return all_results

    async def _handle_failure(
        self,
        node: ExecutionNode,
        ctx: StatelessContext,
        all_results: dict[str, ToolResult],
        layer_results: dict[str, ToolResult],
    ) -> ToolResult:
        """Handle node failure per the spec:

        Level 1: Retry same node (max 1)
        Level 2: Isolate node failure (don't block DAG)
        Level 3: Partial result return (never full restart)
        """
        # Level 1: Retry once
        if node.retry_count < self.MAX_RETRIES:
            node.retry_count += 1
            node.status = ExecutionStatus.RETRYING

            retry_result = await self._runtime.execute_node(
                node, ctx, all_results
            )

            if retry_result.success:
                retry_result.retry_count = node.retry_count
                return retry_result

        # Level 2: Isolate — return failure, don't block parent DAG
        # Level 3: Return partial result (original failure)
        return layer_results.get(node.id) or ToolResult(
            node_id=node.id,
            tool=node.tool,
            success=False,
            error=f"Node '{node.id}' failed after {node.retry_count} retries",
        )
