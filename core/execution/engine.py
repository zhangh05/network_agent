"""
ExecutionEngine — Stateless event emitter.

Invariants:
  - engine.state == NONE (no internal mutable state)
  - No retry counter (retry is re-emitting events)
  - No internal cache
  - No progress state
  - No temporary tool results storage

Architecture:
  ExecutionEngine.execute(plan, run_id, emit, handlers)
    → for each node: emit(NODE_STARTED), invoke handler, emit(NODE_COMPLETED|NODE_FAILED)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable, ClassVar

from core.graph.graph_store import EventType


# ── Pure data types ────────────────────────────────────────────────────

@dataclass(frozen=True)
class ExecutionNode:
    node_id: str
    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    deps: list[str] = field(default_factory=list)
    depth: int = 0


@dataclass(frozen=True)
class ExecutionPlan:
    nodes: tuple[ExecutionNode, ...]
    layers: dict[int, tuple[ExecutionNode, ...]] = field(default_factory=dict)
    max_depth: int = 0
    total_nodes: int = 0

    @classmethod
    def from_plan_dicts(cls, plan_nodes: list[dict]) -> "ExecutionPlan":
        nodes = tuple(
            ExecutionNode(
                node_id=n["id"], tool=n["tool"],
                args=n.get("args", {}), deps=n.get("deps", []),
            )
            for n in plan_nodes
        )
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

        nodes = tuple(
            ExecutionNode(
                node_id=n.node_id, tool=n.tool, args=n.args,
                deps=n.deps, depth=depth_map.get(n.node_id, 0),
            )
            for n in nodes
        )
        max_depth = max((n.depth for n in nodes), default=0)
        layers: dict[int, tuple[ExecutionNode, ...]] = {}
        for n in nodes:
            layers.setdefault(n.depth, ())
            layers[n.depth] = layers[n.depth] + (n,)

        return cls(nodes=nodes, layers=layers, max_depth=max_depth,
                   total_nodes=len(nodes))


@dataclass(frozen=True)
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


# ── Event emitter type ─────────────────────────────────────────────────

EmitFn = Callable[[str, str, dict], None]


# ── ExecutionEngine (STATELESS) ────────────────────────────────────────

Handler = Callable[[dict[str, Any]], Any]


class ExecutionEngine:
    """Pure stateless execution. Zero internal state.

    USAGE:
      engine = ExecutionEngine()
      results = await engine.execute(plan, run_id, emit, handlers)

    The engine is a FUNCTION, not an object with state.
    It can be shared across all runs with no side effects.
    """

    # Class-level assertion: no instance state allowed
    INSTANCE_FIELDS_BANNED: ClassVar[set[str]] = {
        "retry_counter", "cache", "progress", "store", "state", "_results",
    }

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        for name in cls.INSTANCE_FIELDS_BANNED:
            if hasattr(cls, name):
                raise AssertionError(f"ExecutionEngine has banned field: {name}")

    @staticmethod
    async def execute(
        plan: ExecutionPlan,
        run_id: str,
        emit: EmitFn,
        handlers: dict[str, Handler],
    ) -> dict[str, ToolResult]:
        """Execute a plan. PURE FUNCTION — no side effects on engine.

        All state goes through emit() → GraphStore events.
        """
        emit(EventType.STAGE_STARTED, run_id, {"stage": "execute"})
        all_results: dict[str, ToolResult] = {}

        for depth in range(plan.max_depth + 1):
            layer = plan.layers.get(depth, ())
            if not layer:
                continue

            emit(EventType.LAYER_STARTED, run_id, {
                "depth": depth, "node_count": len(layer),
            })

            layer_results = await _execute_layer(
                layer, all_results, run_id, emit, handlers,
            )
            all_results.update(layer_results)

            emit(EventType.LAYER_COMPLETED, run_id, {"depth": depth})

        emit(EventType.STAGE_ENDED, run_id, {"stage": "execute"})
        return all_results


# ── Pure functions (no class, no state) ────────────────────────────────

async def _execute_layer(
    nodes: tuple[ExecutionNode, ...],
    dep_results: dict[str, ToolResult],
    run_id: str,
    emit: EmitFn,
    handlers: dict[str, Handler],
) -> dict[str, ToolResult]:
    tasks = {
        n.node_id: asyncio.create_task(
            _execute_node(n, dep_results, run_id, emit, handlers)
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
    node: ExecutionNode,
    dep_results: dict[str, ToolResult],
    run_id: str,
    emit: EmitFn,
    handlers: dict[str, Handler],
) -> ToolResult:
    import time

    args = _resolve_deps(node.args, dep_results)

    emit(EventType.NODE_STARTED, run_id, {
        "node_id": node.node_id, "tool": node.tool,
    })

    start = time.monotonic()
    try:
        handler = handlers.get(node.tool)
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
        elapsed = (time.monotonic() - start) * 1000
        tr = ToolResult(
            node_id=node.node_id, tool=node.tool,
            success=False, error=str(e), latency_ms=elapsed,
        )
        emit(EventType.NODE_FAILED, run_id, {
            "node_id": node.node_id, "error": str(e),
        })
        return tr


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
                resolved[key] = dep_results[dep_node_id].data
    return resolved


# ── Invariant check ────────────────────────────────────────────────────

def assert_stateless(engine: ExecutionEngine) -> bool:
    """Assert engine has zero mutable state."""
    vars_dict = vars(engine)
    for name in ExecutionEngine.INSTANCE_FIELDS_BANNED:
        if name in vars_dict:
            raise AssertionError(f"ExecutionEngine has banned state: {name}")
    return True
