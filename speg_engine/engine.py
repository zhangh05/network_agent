"""
SPEG Engine — Single-pass Execution Graph Engine (top-level orchestrator).

The ONLY entry point for agent execution. This replaces the entire old
TurnRunner + ContextPipeline + ToolExecutionPipeline stack.

Execution flow:
  USER REQUEST
    → Planner (1 LLM call)
    → Graph Compiler (deterministic)
    → DAG Validator (strict)
    → Execution Engine (async parallel)
    → Result Merger (structured)
    → Finalizer (optional 1 LLM call)
    → SPEGResult

LLM calls: 1 (planner) + 0-1 (finalizer) = max 2 per request.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Callable

from .dag_validator import DAGValidator
from .execution_engine import ExecutionEngine
from .finalizer import Finalizer
from .graph_compiler import GraphCompiler
from .models import SPEGConfig, SPEGResult, StatelessContext, ToolResult
from .planner import Planner
from .result_merger import ResultMerger
from .tool_runtime import ToolRuntime


class SPEGEngine:
    """Single-pass Execution Graph Engine — the complete Agent Runtime.

    Usage:
        engine = SPEGEngine(config, llm_invoke_fn, tool_registry, tool_runtime)
        result = await engine.run(user_input, workspace_id, session_id)
    """

    def __init__(
        self,
        config: SPEGConfig | None = None,
        llm_invoke: Callable[..., str] | None = None,
        tool_registry: dict[str, dict[str, Any]] | None = None,
        tool_runtime: ToolRuntime | None = None,
    ):
        self._config = config or SPEGConfig()
        self._llm_invoke = llm_invoke or self._noop_llm
        self._tool_registry = tool_registry or {}
        self._tool_runtime = tool_runtime or ToolRuntime(self._config)

        # Sub-modules
        self._planner = Planner(self._config, self._tool_registry, self._llm_invoke)
        self._compiler = GraphCompiler(self._config)
        self._validator = DAGValidator(self._config, self._tool_registry)
        self._executor = ExecutionEngine(self._config, self._tool_runtime)
        self._merger = ResultMerger()
        self._finalizer = Finalizer(self._config, self._llm_invoke)

    @property
    def config(self) -> SPEGConfig:
        return self._config

    @property
    def tool_runtime(self) -> ToolRuntime:
        return self._tool_runtime

    def register_tool(
        self,
        tool_id: str,
        handler,
        description: str = "",
        args_schema: dict[str, Any] | None = None,
    ) -> None:
        """Register a tool with both the registry (for planner) and runtime (for execution)."""
        self._tool_registry[tool_id] = {
            "description": description,
            "args_schema": args_schema or {},
        }
        self._tool_runtime.register(tool_id, handler)

    async def run(
        self,
        user_input: str,
        workspace_id: str = "default",
        session_id: str = "",
        cwd: str = "",
    ) -> SPEGResult:
        """Execute a single user request through the SPEG pipeline.

        This is the ONE AND ONLY entry point. No multi-turn loops,
        no context rebuilds, no sequential tool chains.

        Args:
            user_input: The user's request string
            workspace_id: Workspace identifier
            session_id: Session identifier (auto-generated if empty)
            cwd: Current working directory

        Returns:
            SPEGResult with full execution details and final response.
        """
        t_start = time.monotonic()
        request_id = str(uuid.uuid4())[:8]

        errors: list[str] = []
        node_results: dict[str, ToolResult] = {}
        final_response = ""
        planner_latency = 0.0
        execution_latency = 0.0
        merge_latency = 0.0
        finalizer_latency = 0.0
        max_layer_latency = 0.0

        # Build minimal context
        ctx = StatelessContext(
            workspace_id=workspace_id,
            session_id=session_id or f"session_{uuid.uuid4().hex[:12]}",
            request_id=request_id,
            user_input=user_input,
            cwd=cwd,
        )

        try:
            # Phase 1: Plan (1 LLM call)
            plan_nodes = self._planner.plan(ctx)
            planner_latency = ctx.extras.get("planner_latency_ms", 0)

            if not plan_nodes:
                # No tools needed — skip to finalizer
                merged = {"total_nodes": 0, "success_count": 0, "failure_count": 0,
                          "results_by_category": {}, "all_results": {}}
                final_response = await self._finalizer.finalize(ctx, merged)
            else:
                # Phase 2: Compile graph
                dag = self._compiler.compile(plan_nodes)

                # Phase 3: Validate DAG
                dag = self._validator.validate(dag)

                if not dag.is_valid:
                    errors = dag.validation_errors
                    # Return SPEGResult with validation errors
                    return SPEGResult(
                        request_id=request_id,
                        success=False,
                        total_latency_ms=(time.monotonic() - t_start) * 1000,
                        planner_latency_ms=planner_latency,
                        errors=errors,
                        metadata={"dag_status": dag.status.value},
                    )

                # Phase 4: Execute DAG (async parallel)
                node_results = await self._executor.execute(dag, ctx)
                execution_latency = ctx.extras.get("execution_latency_ms", 0)
                max_layer_latency = self._compute_max_layer_latency(dag, node_results)

                # Phase 5: Merge results
                merged = self._merger.merge(dag, node_results, ctx)
                merge_latency = ctx.extras.get("merge_latency_ms", 0)

                # Phase 6: Finalize (optional 1 LLM call)
                final_response = await self._finalizer.finalize(ctx, merged)
                finalizer_latency = ctx.extras.get("finalizer_latency_ms", 0)

        except ValueError as e:
            errors.append(f"Planner error: {e}")
        except Exception as e:
            errors.append(f"Engine error: {type(e).__name__}: {e}")

        total_latency = (time.monotonic() - t_start) * 1000

        return SPEGResult(
            request_id=request_id,
            success=len(errors) == 0 and all(
                r.success for r in node_results.values()
            ),
            total_latency_ms=total_latency,
            planner_latency_ms=planner_latency,
            execution_latency_ms=execution_latency,
            merge_latency_ms=merge_latency,
            finalizer_latency_ms=finalizer_latency,
            max_layer_latency_ms=max_layer_latency,
            node_results=node_results,
            final_response=final_response,
            errors=errors,
            metadata={
                "workspace_id": workspace_id,
                "session_id": ctx.session_id,
                "node_success_count": sum(1 for r in node_results.values() if r.success),
                "node_failure_count": sum(1 for r in node_results.values() if not r.success),
            },
        )

    def _noop_llm(self, **kwargs) -> str:
        """Placeholder LLM invoke when no real LLM is configured."""
        return '{"nodes": []}'

    def _compute_max_layer_latency(
        self,
        dag,
        node_results: dict[str, ToolResult],
    ) -> float:
        """Compute the maximum latency across all execution layers.

        This is the bottleneck layer latency — the key metric for
        parallel execution efficiency.
        """
        max_layer = 0.0
        # Collect nodes by depth
        depth_nodes: dict[int, list] = {}
        for node in dag.nodes:
            if node.depth not in depth_nodes:
                depth_nodes[node.depth] = []
            depth_nodes[node.depth].append(node)

        for nodes in depth_nodes.values():
            layer_latency = max(
                (node_results.get(n.id, ToolResult(
                    node_id=n.id, tool=n.tool, success=False
                )).latency_ms for n in nodes),
                default=0,
            )
            max_layer = max(max_layer, layer_latency)

        return max_layer
