"""
Stateless Tool Runtime — pure function style execution.

Key rules:
  - Tool must be pure function style: execute_tool(name, args) → result
  - No hidden shared state
  - No implicit context access
  - All independent executions are concurrent
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable

from .models import ExecutionNode, ExecutionStatus, SPEGConfig, StatelessContext, ToolResult

ToolHandler = Callable[[dict[str, Any]], Any | Awaitable[Any]]


class ToolRuntime:
    """Stateless tool execution runtime.

    Tools are registered as handler functions. Each handler receives
    arguments and returns results — no shared state, no implicit context.
    """

    def __init__(self, config: SPEGConfig):
        self._config = config
        self._handlers: dict[str, ToolHandler] = {}

    def register(self, tool_id: str, handler: ToolHandler) -> None:
        """Register a tool handler.

        Handler signature: handler(args: dict) → result | Awaitable[result]
        """
        self._handlers[tool_id] = handler

    def has_tool(self, tool_id: str) -> bool:
        return tool_id in self._handlers

    async def execute_node(
        self,
        node: ExecutionNode,
        ctx: StatelessContext,
        dep_results: dict[str, ToolResult],
    ) -> ToolResult:
        """Execute a single node with dependency injection.

        Args:
            node: The compiled execution node
            ctx: Minimal stateless context
            dep_results: Resolved results of this node's dependencies

        Returns:
            ToolResult with success/failure and data
        """
        start = time.monotonic()

        if node.tool not in self._handlers:
            elapsed = (time.monotonic() - start) * 1000
            return ToolResult(
                node_id=node.id,
                tool=node.tool,
                success=False,
                error=f"Tool '{node.tool}' has no registered handler",
                latency_ms=elapsed,
                retry_count=0,
            )

        # Inject dependency results into args
        merged_args = self._merge_dep_results(node.args, dep_results)

        try:
            handler = self._handlers[node.tool]
            # Run with timeout
            result = await asyncio.wait_for(
                self._invoke_handler(handler, merged_args),
                timeout=self._config.single_node_timeout_ms / 1000,
            )
            elapsed = (time.monotonic() - start) * 1000
            return ToolResult(
                node_id=node.id,
                tool=node.tool,
                success=True,
                data=result,
                latency_ms=elapsed,
                retry_count=node.retry_count,
            )
        except asyncio.TimeoutError:
            elapsed = (time.monotonic() - start) * 1000
            return ToolResult(
                node_id=node.id,
                tool=node.tool,
                success=False,
                error=f"Tool execution timed out after {self._config.single_node_timeout_ms}ms",
                latency_ms=elapsed,
                retry_count=node.retry_count,
            )
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            return ToolResult(
                node_id=node.id,
                tool=node.tool,
                success=False,
                error=f"{type(e).__name__}: {e}",
                latency_ms=elapsed,
                retry_count=node.retry_count,
            )

    async def execute_layer(
        self,
        nodes: list[ExecutionNode],
        ctx: StatelessContext,
        dep_results: dict[str, ToolResult],
    ) -> dict[str, ToolResult]:
        """Execute all nodes in a layer concurrently.

        All nodes at the same depth run fully parallel via asyncio.gather.
        """
        if not nodes:
            return {}

        tasks = {
            node.id: asyncio.create_task(
                self.execute_node(node, ctx, dep_results)
            )
            for node in nodes
        }

        results = await asyncio.gather(*tasks.values(), return_exceptions=True)

        layer_results: dict[str, ToolResult] = {}
        for node_id, result in zip(tasks.keys(), results):
            if isinstance(result, Exception):
                layer_results[node_id] = ToolResult(
                    node_id=node_id,
                    tool="unknown",
                    success=False,
                    error=f"{type(result).__name__}: {result}",
                )
            else:
                layer_results[node_id] = result

        return layer_results

    async def _invoke_handler(self, handler: ToolHandler, args: dict[str, Any]) -> Any:
        """Invoke a handler, supporting both sync and async handlers."""
        result = handler(args)
        if asyncio.iscoroutine(result):
            result = await result
        return result

    def _merge_dep_results(
        self,
        args: dict[str, Any],
        dep_results: dict[str, ToolResult],
    ) -> dict[str, Any]:
        """Inject dependency results into node arguments.

        If an arg value is a special reference like "$dep.node_id.data",
        replace it with the actual dependency result.
        """
        merged = dict(args)
        for key, value in list(merged.items()):
            if isinstance(value, str) and value.startswith("$dep."):
                # Resolve dependency: "$dep.node_id.data"
                parts = value.replace("$dep.", "").split(".", 1)
                dep_id = parts[0]
                if dep_id in dep_results:
                    dep_result = dep_results[dep_id]
                    if len(parts) > 1 and parts[1] == "data":
                        merged[key] = dep_result.data
                    else:
                        merged[key] = dep_result.data
        return merged
