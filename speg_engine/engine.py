"""
SPEG Engine — Production-grade 15-stage pipeline.

Bank-grade SPEG Runtime v1:
  controllable, auditable, recoverable, rate-limited, traceable, verifiable.

Pipeline stages:
  1. create_request_context
  2. build_minimal_context
  3. planner_generate_graph
  4. compile_graph
  5. structural_validate_graph (DAGValidator)
  6. semantic_validate_graph (SemanticValidator)
  7. risk_policy_check (RiskPolicyEngine)
  8. budget_check (BudgetController)
  9. schedule_and_execute (Scheduler + ExecutionEngine)
  10. repair_if_needed (RepairEngine)
  11. rollback_assessment (RollbackEngine)
  12. merge_results (ResultMerger)
  13. finalizer_optional
  14. audit_write (AuditLogger)
  15. metrics_emit + return_response

Any stage failure returns structured SPEGError — no raw exceptions.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Callable

from .audit import AuditLogger
from .budget_controller import BudgetController
from .contracts import BUILTIN_CONTRACTS
from .dag_validator import DAGValidator
from .errors import SPEGError, SpegErrorCode, build_error
from .execution_engine import ExecutionEngine
from .finalizer import Finalizer
from .graph_compiler import GraphCompiler
from .metrics import MetricsCollector
from .models import (
    ExecutionNode,
    ExecutionStatus,
    SPEGConfig,
    SPEGResult,
    StatelessContext,
    ToolResult,
)
from .planner import Planner
from .repair_engine import RepairEngine
from .result_merger import ResultMerger
from .risk_policy import RiskPolicyEngine
from .rollback import RollbackEngine
from .scheduler import ResourceScheduler
from .semantic_validator import SemanticValidator
from .tool_runtime import ToolRuntime
from .trace import SpanClock, TraceCollector


class SPEGEngine:
    """Bank-grade Single-pass Execution Graph Engine — production runtime.

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

        # Pipeline modules
        self._planner = Planner(self._config, self._tool_registry, self._llm_invoke)
        self._compiler = GraphCompiler(self._config)
        self._struct_validator = DAGValidator(self._config, self._tool_registry)
        self._sem_validator = SemanticValidator(self._tool_registry)
        self._risk_policy = RiskPolicyEngine()
        self._scheduler = ResourceScheduler(self._config)
        self._executor = ExecutionEngine(self._config, self._tool_runtime)
        self._repair = RepairEngine(self._config)
        self._rollback = RollbackEngine()
        self._merger = ResultMerger()
        self._finalizer = Finalizer(self._config, self._llm_invoke)
        self._audit = AuditLogger()
        self._trace = TraceCollector()

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
        self._tool_registry[tool_id] = {
            "description": description,
            "args_schema": args_schema or {},
        }
        self._tool_runtime.register(tool_id, handler)

    # ========================================================================
    # 15-STAGE PRODUCTION PIPELINE
    # ========================================================================

    async def run(
        self,
        user_input: str,
        workspace_id: str = "default",
        session_id: str = "",
        cwd: str = "",
    ) -> SPEGResult:
        """Execute a single user request through the 15-stage bank-grade pipeline."""
        t_total = time.monotonic()
        metrics = MetricsCollector()
        budget = BudgetController(self._config)
        request_span = self._trace.start_request(str(uuid.uuid4())[:8])

        # Stage 1 & 2: Context
        ctx = StatelessContext(
            workspace_id=workspace_id,
            session_id=session_id or f"session_{uuid.uuid4().hex[:12]}",
            request_id=request_span.span.metadata.get("request_id", "unknown"),
            user_input=user_input,
            cwd=cwd,
        )

        errors: list[SPEGError] = []
        node_results: dict[str, ToolResult] = {}
        final_response = ""
        dag = None
        risk_level = "low"
        approval_required = False
        rollback_plan = None

        try:
            # Stage 3: Planner (1 LLM call)
            budget_result = budget.check_planner()
            if not budget_result.ok:
                raise ValueError(f"Budget: {budget_result.exceeded}")

            llm_budget = budget.check_llm_call()
            if not llm_budget.ok:
                raise ValueError(f"Budget: {llm_budget.exceeded}")

            t_planner = time.monotonic()
            plan_nodes = self._planner.plan(ctx)
            metrics.capture_planner((time.monotonic() - t_planner) * 1000)

            if not plan_nodes:
                # No tools — skip to finalizer
                t_merge = time.monotonic()
                merged = {"total_nodes": 0, "success_count": 0, "failure_count": 0,
                          "results_by_category": {}, "all_results": {}}
                metrics.capture_compile(0)
                metrics.capture_validation(0)

                direct_response = str(ctx.extras.get("direct_response") or "").strip()
                if direct_response:
                    final_response = direct_response
                    metrics.capture_finalizer(0)
                else:
                    final_budget = budget.check_finalizer()
                    if final_budget.ok and self._config.enable_finalizer:
                        llm_budget2 = budget.check_llm_call()
                        if llm_budget2.ok:
                            final_response = await self._finalizer.finalize(ctx, merged)
                            metrics.capture_finalizer(
                                float(ctx.extras.get("finalizer_latency_ms", 0))
                            )
                        else:
                            final_response = "No tools needed. (finalizer budget exceeded)"
                    else:
                        final_response = self._finalizer._build_default_response(merged)

                metrics.set_llm_calls(budget.llm_calls)
                dag = None
            else:
                # Stage 4: Compile
                t_compile = time.monotonic()
                dag = self._compiler.compile(plan_nodes)
                metrics.capture_compile((time.monotonic() - t_compile) * 1000)

                # Budget: check DAG
                dag_budget = budget.check_dag(dag)
                if not dag_budget.ok:
                    errors.append(build_error(
                        SpegErrorCode.BUDGET_NODES_EXCEEDED,
                        f"DAG budget exceeded: {dag_budget.exceeded}",
                        stage="budget_check",
                    ))
                    return self._build_result(ctx, dag, node_results, final_response,
                                              errors, metrics, budget, t_total, risk_level, approval_required)

                # Stage 5: Structural validation
                t_val = time.monotonic()
                dag = self._struct_validator.validate(dag)
                metrics.capture_validation((time.monotonic() - t_val) * 1000)

                if not dag.is_valid:
                    for e in dag.validation_errors:
                        errors.append(build_error(
                            SpegErrorCode.VALIDATION_TOOL_NOT_FOUND, e,
                            stage="structural_validate",
                        ))
                    return self._build_result(ctx, dag, node_results, final_response,
                                              errors, metrics, budget, t_total, risk_level, approval_required)

                # Stage 6: Semantic validation
                t_sem = time.monotonic()
                sem_result = self._sem_validator.validate(dag)
                if not sem_result.valid:
                    for e in sem_result.errors:
                        errors.append(build_error(
                            e.code, e.message,
                            stage="semantic_validate", node_id=e.node_id,
                        ))
                    return self._build_result(ctx, dag, node_results, final_response,
                                              errors, metrics, budget, t_total, sem_result.risk_level, approval_required)

                risk_level = sem_result.risk_level

                # Stage 7: Risk policy check
                risk_assessment = self._risk_policy.assess(dag)
                risk_level = risk_assessment.risk_level
                if not risk_assessment.safe_to_run:
                    errors.append(build_error(
                        SpegErrorCode.RISK_CRITICAL_DENIED,
                        risk_assessment.blocked_reason,
                        stage="risk_policy",
                    ))
                    return self._build_result(ctx, dag, node_results, final_response,
                                              errors, metrics, budget, t_total, risk_level, risk_assessment.requires_approval)
                approval_required = risk_assessment.requires_approval

                # Stage 8: Budget re-check
                exec_budget = budget.check_execution()
                if not exec_budget.ok:
                    errors.append(build_error(
                        SpegErrorCode.BUDGET_TIME_EXCEEDED,
                        f"Execution budget: {exec_budget.exceeded}",
                        stage="budget_check",
                    ))
                    return self._build_result(ctx, dag, node_results, final_response,
                                              errors, metrics, budget, t_total, risk_level, approval_required)

                # Stage 9: Schedule and execute
                t_exec = time.monotonic()
                execution_span = self._trace.add_span("execution", dag_nodes=dag.total_nodes)

                node_results = await self._scheduled_execute(dag, ctx, budget)
                execution_ms = (time.monotonic() - t_exec) * 1000
                execution_span.stop()
                metrics.capture_execution(execution_ms, node_results, dag)

                # Stage 10: Repair if needed
                repair_spans = []
                for node in dag.nodes:
                    result = node_results.get(node.id)
                    if result and not result.success:
                        repair = self._repair.assess(node, result, dag)
                        if repair.strategy == "retry":
                            node.retry_count += 1
                            retry_span = self._trace.add_node_span(node)
                            retry_result = await self._tool_runtime.execute_node(node, ctx, node_results)
                            retry_span.stop(status="ok" if retry_result.success else "error")
                            node_results[node.id] = retry_result
                            repair_spans.append(retry_span)

                # Stage 11: Rollback assessment
                rollback_plan = self._rollback.assess(dag, node_results)

                # Stage 12: Merge results
                t_merge = time.monotonic()
                merged = self._merger.merge(dag, node_results, ctx)

                # Stage 13: Finalizer (optional 1 LLM call)
                final_budget = budget.check_finalizer()
                if final_budget.ok and self._config.enable_finalizer:
                    llm_budget2 = budget.check_llm_call()
                    if llm_budget2.ok:
                        llm_span = self._trace.add_span("finalizer")
                        t_final = time.monotonic()
                        final_response = await self._finalizer.finalize(ctx, merged)
                        llm_span.stop()
                        metrics.capture_finalizer(
                            float(ctx.extras.get("finalizer_latency_ms", 0))
                        )
                else:
                    final_response = self._finalizer._build_default_response(merged)

            metrics.set_llm_calls(budget.llm_calls)
            metrics.set_risk_level(risk_level)

        except Exception as e:
            errors.append(build_error(
                "ENGINE_PANIC", f"{type(e).__name__}: {e}",
                stage="engine", risk_level="high",
            ))

        return self._build_result(
            ctx, dag, node_results, final_response,
            errors, metrics, budget, t_total, risk_level, approval_required,
            rollback_plan,
        )

    # ========================================================================
    # Scheduled execution with concurrency control
    # ========================================================================

    async def _scheduled_execute(
        self,
        dag,
        ctx: StatelessContext,
        budget: BudgetController,
    ) -> dict[str, ToolResult]:
        """Execute DAG layer by layer with ResourceScheduler concurrency control."""
        all_results: dict[str, ToolResult] = {}
        active_global = 0

        for depth in range(dag.max_depth + 1):
            layer_nodes = dag.get_layer(depth)
            if not layer_nodes:
                continue

            # Mark pending
            for node in layer_nodes:
                node.status = ExecutionStatus.PENDING

            # Schedule: apply concurrency limits
            ready = self._scheduler.schedule_layer(layer_nodes, active_global)
            if not ready:
                # All nodes at this depth are waiting for resources
                ready = layer_nodes

            # Execute batch
            for node in ready:
                node.status = ExecutionStatus.RUNNING
                node.started_at = time.monotonic()

            active_global += len(ready)
            layer_results = await self._tool_runtime.execute_layer(ready, ctx, all_results)

            # Process results
            for node in ready:
                result = layer_results.get(node.id)
                if result is None:
                    result = ToolResult(node_id=node.id, tool=node.tool, success=False,
                                        error="No result returned")
                node.result = result.data
                node.error = result.error
                node.status = ExecutionStatus.SUCCESS if result.success else ExecutionStatus.FAILED
                node.latency_ms = result.latency_ms
                node.finished_at = time.monotonic()
                all_results[node.id] = result

            active_global -= len(ready)

            # Budget check between layers
            b = budget.check_execution()
            if not b.ok:
                break

        return all_results

    # ========================================================================
    # Result assembly
    # ========================================================================

    def _build_result(
        self,
        ctx: StatelessContext,
        dag,
        node_results: dict[str, ToolResult],
        final_response: str,
        errors: list[SPEGError],
        metrics: MetricsCollector,
        budget: BudgetController,
        t_total: float,
        risk_level: str,
        approval_required: bool,
        rollback_plan=None,
    ) -> SPEGResult:
        total_ms = (time.monotonic() - t_total) * 1000
        metrics.capture_total(total_ms)
        self._mark_blocked_nodes_for_audit(dag, node_results, errors)
        self._audit.create_record(
            ctx, dag, node_results,
            risk_level=risk_level,
            approval_required=approval_required,
            llm_call_count=budget.llm_calls,
            duration_ms=total_ms,
        )
        m = metrics.snapshot()

        return SPEGResult(
            request_id=ctx.request_id,
            success=len(errors) == 0,
            total_latency_ms=total_ms,
            planner_latency_ms=m.planner_duration_ms,
            execution_latency_ms=m.execution_duration_ms,
            merge_latency_ms=0.0,
            finalizer_latency_ms=m.finalizer_duration_ms,
            max_layer_latency_ms=0.0,
            node_results=node_results,
            final_response=final_response,
            errors=[e.message for e in errors],
            metadata={
                "workspace_id": ctx.workspace_id,
                "session_id": ctx.session_id,
                "node_success_count": sum(1 for r in node_results.values() if r.success),
                "node_failure_count": sum(1 for r in node_results.values() if not r.success),
                "all_nodes_success": all(r.success for r in node_results.values()) if node_results else True,
                "risk_level": risk_level,
                "approval_required": approval_required,
                "llm_calls": budget.llm_calls,
                "dag_nodes": dag.total_nodes if dag else 0,
                "dag_depth": dag.max_depth if dag else 0,
                "structured_errors": [e.to_dict() for e in errors],
                "metrics": metrics.to_dict(),
                "rollback_available": rollback_plan.rollback_available if rollback_plan else False,
                "rollback_recommended": rollback_plan.rollback_recommended if rollback_plan else False,
            },
        )

    @staticmethod
    def _mark_blocked_nodes_for_audit(
        dag,
        node_results: dict[str, ToolResult],
        errors: list[SPEGError],
    ) -> None:
        if not dag:
            return
        error_node_ids = {e.node_id for e in errors if e.node_id}
        for node in dag.nodes:
            if node.id in node_results:
                continue
            if node.status in (ExecutionStatus.SUCCESS, ExecutionStatus.FAILED):
                continue
            if node.id in error_node_ids:
                node.status = ExecutionStatus.SKIPPED

    def _noop_llm(self, **kwargs) -> str:
        return '{"nodes": []}'
