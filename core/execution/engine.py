"""
ExecutionEngine — Pure event emitter.

Rules:
  - ONLY emit events (ToolEvent, NodeEvent, etc.)
  - NEVER write to GraphStore directly
  - NEVER compute timing
  - NEVER mutate plan state
  - All side effects go through event callbacks

Architecture:
  ExecutionEngine.run(plan, emit)
    → for each layer, for each node:
        emit(NodeStarted)
        result = invoke_tool(...)
        emit(NodeCompleted | NodeFailed)
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

from core.graph.graph_store import EventType


# ── Data types ───────────────────────────────────────────────────────

@dataclass
class ExecutionNode:
    """A single node to execute."""
    node_id: str
    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    deps: list[str] = field(default_factory=list)
    depth: int = 0


@dataclass
class ExecutionPlan:
    """Pre-compiled DAG ready for execution."""
    nodes: list[ExecutionNode]
    layers: dict[int, list[ExecutionNode]] = field(default_factory=dict)
    max_depth: int = 0
    total_nodes: int = 0

    @classmethod
    def from_plan_dicts(cls, plan_nodes: list[dict]) -> "ExecutionPlan":
        nodes = [
            ExecutionNode(
                node_id=n["id"],
                tool=n["tool"],
                args=n.get("args", {}),
                deps=n.get("deps", []),
            )
            for n in plan_nodes
        ]
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

        return cls(nodes=nodes, layers=layers, max_depth=max_depth,
                   total_nodes=len(nodes))


@dataclass
class ToolResult:
    node_id: str
    tool: str
    success: bool
    data: Any = None
    error: str | None = None
    latency_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id, "tool": self.tool,
            "success": self.success, "data": self.data,
            "error": self.error, "latency_ms": self.latency_ms,
        }


# ── Event emitter callback type ──────────────────────────────────────

EmitFn = Callable[[str, str, dict], None]
"""emit(event_type: str, run_id: str, payload: dict) -> None"""


# ── ExecutionEngine ──────────────────────────────────────────────────

Handler = Callable[[dict[str, Any]], Any]
AsyncHandler = Callable[[dict[str, Any]], Awaitable[Any]]


class ExecutionEngine:
    """Pure execution. Emits events. No state mutation."""

    def __init__(self, handlers: dict[str, Handler | AsyncHandler] | None = None):
        self._handlers: dict[str, Handler | AsyncHandler] = handlers or {}
        self._max_retries: int = 1

    def register(self, tool: str, handler: Handler | AsyncHandler) -> None:
        self._handlers[tool] = handler

    async def execute(
        self,
        plan: ExecutionPlan,
        run_id: str,
        emit: EmitFn,
    ) -> dict[str, ToolResult]:
        """Execute a plan. Emits events for every action. No state writes.

        Args:
            plan: The execution plan with pre-compiled DAG
            run_id: Current run identifier
            emit: Event callback (event_type, run_id, payload)
        """
        emit(EventType.STAGE_STARTED, run_id, {"stage": "execute"})

        all_results: dict[str, ToolResult] = {}

        for depth in range(plan.max_depth + 1):
            layer = plan.layers.get(depth, [])
            if not layer:
                continue

            emit(EventType.LAYER_STARTED, run_id, {
                "depth": depth, "node_count": len(layer),
            })

            layer_results = await self._execute_layer(layer, all_results, run_id, emit)
            all_results.update(layer_results)

            emit(EventType.LAYER_COMPLETED, run_id, {"depth": depth})

        emit(EventType.STAGE_ENDED, run_id, {"stage": "execute"})
        return all_results

    async def _execute_layer(
        self,
        nodes: list[ExecutionNode],
        dep_results: dict[str, ToolResult],
        run_id: str,
        emit: EmitFn,
    ) -> dict[str, ToolResult]:
        """Execute all nodes in one layer concurrently."""
        tasks = {
            n.node_id: asyncio.create_task(
                self._execute_node(n, dep_results, run_id, emit)
            )
            for n in nodes
        }
        gathered = await asyncio.gather(*tasks.values(), return_exceptions=True)

        results: dict[str, ToolResult] = {}
        for node_id, result in zip(tasks.keys(), gathered):
            if isinstance(result, Exception):
                results[node_id] = ToolResult(
                    node_id=node_id, tool="unknown",
                    success=False, error=f"{type(result).__name__}: {result}",
                )
            else:
                results[node_id] = result
        return results

    async def _execute_node(
        self,
        node: ExecutionNode,
        dep_results: dict[str, ToolResult],
        run_id: str,
        emit: EmitFn,
    ) -> ToolResult:
        """Execute a single node. Emit NODE_STARTED + (NODE_COMPLETED | NODE_FAILED)."""
        args = self._resolve_deps(node.args, dep_results)

        emit(EventType.NODE_STARTED, run_id, {
            "node_id": node.node_id, "tool": node.tool,
        })

        last_error = None
        for attempt in range(self._max_retries + 1):
            start = time.monotonic()
            try:
                handler = self._handlers.get(node.tool)
                if handler is None:
                    raise RuntimeError(f"No handler for {node.tool}")

                result = handler(args)
                if asyncio.iscoroutine(result):
                    result = await result

                elapsed = (time.monotonic() - start) * 1000
                tr = ToolResult(
                    node_id=node.node_id, tool=node.tool,
                    success=True, data=result, latency_ms=elapsed,
                )
                emit(EventType.NODE_COMPLETED, run_id, {
                    "node_id": node.node_id, "result": tr.to_dict(),
                })
                return tr

            except Exception as e:
                last_error = str(e)
                if attempt == self._max_retries:
                    elapsed = (time.monotonic() - start) * 1000
                    tr = ToolResult(
                        node_id=node.node_id, tool=node.tool,
                        success=False, error=last_error, latency_ms=elapsed,
                    )
                    emit(EventType.NODE_FAILED, run_id, {
                        "node_id": node.node_id, "error": last_error,
                    })
                    return tr

        return ToolResult(
            node_id=node.node_id, tool=node.tool,
            success=False, error=last_error or "unknown",
        )

    @staticmethod
    def _resolve_deps(
        args: dict[str, Any],
        dep_results: dict[str, ToolResult],
    ) -> dict[str, Any]:
        resolved = dict(args)
        for key, value in list(resolved.items()):
            if isinstance(value, str) and value.startswith("$dep."):
                parts = value.replace("$dep.", "").split(".", 1)
                dep_node_id = parts[0]
                if dep_node_id in dep_results:
                    dep_result = dep_results[dep_node_id]
                    resolved[key] = dep_result.data
        return resolved


# ── ToolGateway ────────────────────────────────────────────────────────

class ToolGateway:
    """Unified tool invocation through the event system."""

    @staticmethod
    async def execute(
        tool: str,
        args: dict[str, Any],
        run_id: str,
        emit: EmitFn,
        handlers: dict[str, Handler] | None = None,
    ) -> ToolResult:
        handlers = handlers or {}
        handler = handlers.get(tool)
        if handler is None:
            return ToolResult(node_id="gw", tool=tool, success=False,
                              error=f"No handler for {tool}")

        start = time.monotonic()
        try:
            result = handler(args)
            if asyncio.iscoroutine(result):
                result = await result
            elapsed = (time.monotonic() - start) * 1000
            return ToolResult(node_id="gw", tool=tool, success=True,
                              data=result, latency_ms=elapsed)
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            return ToolResult(node_id="gw", tool=tool, success=False,
                              error=str(e), latency_ms=elapsed)


# ── Singleton ──────────────────────────────────────────────────────────

_engine: ExecutionEngine | None = None


def get_execution_engine() -> ExecutionEngine:
    global _engine
    if _engine is None:
        _engine = ExecutionEngine()
    return _engine
