"""
ExecutionEngine — Pure tool execution layer.

Replaces:
  - engine.py  tool execution + scheduling
  - tool_runtime.py  execute_node / execute_layer
  - scattered retry logic
  - graph mutation inside execution

Rules:
  - NO graph access (reads from ExecutionPlan, returns ToolResults)
  - NO timing logic (uses StageClock.begin/end only as callback)
  - NO state mutation (writes results, doesn't touch GraphStore)
  - NO LLM calls
  - ONLY responsibility: execute tools per plan

Architecture:
  ExecutionPlan → ExecutionEngine.run() → dict[node_id, ToolResult]
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

from core.graph.graph_store import get_graph_store


# ── Data types ───────────────────────────────────────────────────────

@dataclass
class ExecutionNode:
    """A single node to execute."""
    node_id: str
    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    deps: list[str] = field(default_factory=list)
    depth: int = 0
    concurrency_group: str = "default"


@dataclass
class ExecutionPlan:
    """A pre-compiled DAG ready for execution — no extra metadata."""
    nodes: list[ExecutionNode]
    layers: dict[int, list[ExecutionNode]] = field(default_factory=dict)
    max_depth: int = 0
    total_nodes: int = 0

    @classmethod
    def from_plan_dicts(cls, plan_nodes: list[dict]) -> "ExecutionPlan":
        """Build ExecutionPlan from LLM planner output (list of dicts)."""
        nodes = [
            ExecutionNode(
                node_id=n["id"],
                tool=n["tool"],
                args=n.get("args", {}),
                deps=n.get("deps", []),
            )
            for n in plan_nodes
        ]
        # Assign depths via topological sort
        depth_map: dict[str, int] = {}
        changed = True
        while changed:
            changed = False
            for node in nodes:
                if node.node_id in depth_map:
                    continue
                dep_depths = [depth_map[d] for d in node.deps if d in depth_map]
                if not node.deps or len(dep_depths) == len(node.deps):
                    depth_map[node.node_id] = max(dep_depths, default=-1) + 1
                    changed = True

        for node in nodes:
            node.depth = depth_map.get(node.node_id, 0)

        max_depth = max((n.depth for n in nodes), default=0)
        layers: dict[int, list[ExecutionNode]] = {}
        for n in nodes:
            layers.setdefault(n.depth, []).append(n)

        return cls(
            nodes=nodes,
            layers=layers,
            max_depth=max_depth,
            total_nodes=len(nodes),
        )


@dataclass
class ToolResult:
    """Result from a single tool execution."""
    node_id: str
    tool: str
    success: bool
    data: Any = None
    error: str | None = None
    latency_ms: float = 0.0
    retry_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "tool": self.tool,
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "latency_ms": self.latency_ms,
            "retry_count": self.retry_count,
        }


# ── Engine ───────────────────────────────────────────────────────────

Handler = Callable[[dict[str, Any]], Any]
AsyncHandler = Callable[[dict[str, Any]], Awaitable[Any]]


class ExecutionEngine:
    """Pure tool execution. No graph access, no timing mutation.

    execute(plan) → {node_id: ToolResult}
    """

    def __init__(self, handlers: dict[str, Handler | AsyncHandler] | None = None):
        self._handlers: dict[str, Handler | AsyncHandler] = handlers or {}
        self._max_retries: int = 1
        self._layer_concurrency: int = 5

    def register(self, tool: str, handler: Handler | AsyncHandler) -> None:
        self._handlers[tool] = handler

    # ── Core execute ──────────────────────────────────────────

    async def execute(
        self,
        plan: ExecutionPlan,
        on_stage_begin: Callable[[str], None] | None = None,
        on_stage_end: Callable[[str], None] | None = None,
    ) -> dict[str, ToolResult]:
        """Execute a plan layer by layer.

        Same-depth nodes run in parallel. Cross-depth nodes are serial.
        """
        if on_stage_begin:
            on_stage_begin("execute")

        all_results: dict[str, ToolResult] = {}

        for depth in range(plan.max_depth + 1):
            layer = plan.layers.get(depth, [])
            if not layer:
                continue

            layer_results = await self._execute_layer(layer, all_results)
            all_results.update(layer_results)

        if on_stage_end:
            on_stage_end("execute")

        return all_results

    async def _execute_layer(
        self,
        nodes: list[ExecutionNode],
        dep_results: dict[str, ToolResult],
    ) -> dict[str, ToolResult]:
        """Execute all nodes in one layer concurrently."""
        tasks = {
            n.node_id: asyncio.create_task(
                self._execute_node_with_retry(n, dep_results)
            )
            for n in nodes
        }
        gathered = await asyncio.gather(*tasks.values(), return_exceptions=True)

        results: dict[str, ToolResult] = {}
        for node_id, result in zip(tasks.keys(), gathered):
            if isinstance(result, Exception):
                results[node_id] = ToolResult(
                    node_id=node_id,
                    tool="unknown",
                    success=False,
                    error=f"{type(result).__name__}: {result}",
                )
            else:
                results[node_id] = result
        return results

    async def _execute_node_with_retry(
        self,
        node: ExecutionNode,
        dep_results: dict[str, ToolResult],
    ) -> ToolResult:
        """Execute a single node with retry."""
        args = self._resolve_deps(node.args, dep_results)
        last_error = None

        for attempt in range(self._max_retries + 1):
            start = time.monotonic()
            try:
                handler = self._handlers.get(node.tool)
                if handler is None:
                    return ToolResult(
                        node_id=node.node_id,
                        tool=node.tool,
                        success=False,
                        error=f"No handler registered for {node.tool}",
                    )

                result = handler(args)
                if asyncio.iscoroutine(result):
                    result = await result

                elapsed = (time.monotonic() - start) * 1000
                return ToolResult(
                    node_id=node.node_id,
                    tool=node.tool,
                    success=True,
                    data=result,
                    latency_ms=elapsed,
                    retry_count=attempt,
                )

            except Exception as e:
                last_error = str(e)
                if attempt == self._max_retries:
                    elapsed = (time.monotonic() - start) * 1000
                    return ToolResult(
                        node_id=node.node_id,
                        tool=node.tool,
                        success=False,
                        error=last_error,
                        latency_ms=elapsed,
                        retry_count=attempt,
                    )

        # Unreachable, but safety fallback
        return ToolResult(
            node_id=node.node_id,
            tool=node.tool,
            success=False,
            error=last_error or "unknown",
        )

    # ── Dependency injection ───────────────────────────────────

    @staticmethod
    def _resolve_deps(
        args: dict[str, Any],
        dep_results: dict[str, ToolResult],
    ) -> dict[str, Any]:
        """Inject dependency results: $dep.node_id.data → actual value."""
        resolved = dict(args)
        for key, value in list(resolved.items()):
            if isinstance(value, str) and value.startswith("$dep."):
                parts = value.replace("$dep.", "").split(".", 1)
                dep_node_id = parts[0]
                if dep_node_id in dep_results:
                    dep_result = dep_results[dep_node_id]
                    if len(parts) > 1 and parts[1] == "data":
                        resolved[key] = dep_result.data
                    else:
                        resolved[key] = dep_result.data
        return resolved


# ── ToolGateway (unified tool invocation) ─────────────────────────────

class ToolGateway:
    """Unified gateway for tool execution. Replaces direct tool call."""

    def __init__(self, runtime_client=None):
        self._client = runtime_client

    @staticmethod
    async def execute(tool: str, args: dict[str, Any],
                      runtime_client=None) -> ToolResult:
        """Execute a single tool through the gateway."""
        start = time.monotonic()
        try:
            if runtime_client:
                result = await runtime_client.call_tool(tool, args)
            else:
                # Fallback: direct handler lookup
                from core.execution.engine import get_execution_engine
                engine = get_execution_engine()
                result = await engine._execute_node_with_retry(
                    ExecutionNode(node_id="gw", tool=tool, args=args),
                    {},
                )
            elapsed = (time.monotonic() - start) * 1000
            if isinstance(result, ToolResult):
                result.latency_ms = elapsed
                return result
            return ToolResult(
                node_id="gw", tool=tool, success=True,
                data=result, latency_ms=elapsed,
            )
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            return ToolResult(
                node_id="gw", tool=tool, success=False,
                error=str(e), latency_ms=elapsed,
            )


# ── Module singleton ──────────────────────────────────────────────────

_engine: ExecutionEngine | None = None


def get_execution_engine() -> ExecutionEngine:
    global _engine
    if _engine is None:
        _engine = ExecutionEngine()
    return _engine
