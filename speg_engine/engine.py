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
  6b. pre_execution_repair (PreExecutionRepairEngine) — deterministic + LLM
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
from .pre_execution_repair import PreExecutionRepairEngine, PreExecutionRepairResult
from .repair_engine import RepairEngine
from .result_merger import ResultMerger
from .risk_policy import RiskPolicyEngine
from .rollback import RollbackEngine
from .scheduler import ResourceScheduler
from .semantic_validator import SemanticValidator
from .stage_events import (
    BUDGET_OK,
    EXECUTION_COMPLETED,
    EXECUTION_STARTED,
    FINALIZING_COMPLETED,
    FINALIZING_STARTED,
    GRAPH_COMPILED,
    HEARTBEAT,
    MERGE_COMPLETED,
    PLANNER_COMPLETED,
    PLANNER_STARTED,
    PRE_REPAIR_COMPLETED,
    PRE_REPAIR_STARTED,
    REPAIR_ATTEMPT,
    RISK_ASSESSED,
    SEMANTIC_INVALID,
    SEMANTIC_VALIDATED,
    STRUCTURAL_VALIDATED,
    TURN_COMPLETED,
    TURN_STARTED,
)
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
        emitter: Any | None = None,
        heartbeat_interval_s: float = 1.0,
    ):
        self._config = config or SPEGConfig()
        self._llm_invoke = llm_invoke or self._noop_llm
        self._tool_registry = tool_registry or {}
        self._tool_runtime = tool_runtime or ToolRuntime(self._config)
        # Optional emitter — when provided, every stage boundary pushes a
        # tiny status message so the frontend can show progress instead
        # of staring at "思考中…" for 12 seconds on cold-start.
        # Falls back to a no-op so the engine still works in offline tests.
        self._emitter = emitter
        self._heartbeat_interval_s = max(0.5, float(heartbeat_interval_s))
        self._heartbeat_task: asyncio.Task | None = None

        # Pipeline modules
        self._planner = Planner(self._config, self._tool_registry, self._llm_invoke)
        self._compiler = GraphCompiler(self._config)
        self._struct_validator = DAGValidator(self._config, self._tool_registry)
        self._sem_validator = SemanticValidator(self._tool_registry)
        self._pre_exec_repair = PreExecutionRepairEngine()
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

    def _emit_stage(self, stage: str, t_start: float, **extra: Any) -> None:
        """Best-effort emit of a stage event through the injected emitter.

        Stages that don't yet have an emitter (offline tests) fall back
        to a fresh ``StreamEmitter()`` instance — the realtime callback
        itself is class-level thread-local, so even a new instance
        pushes through the callback the WebSocket handler already
        registered in the same worker thread.

        We never raise here — emit failures must not block the pipeline.
        """
        if self._emitter is None:
            try:
                from agent.runtime.query_engine import StreamEmitter
            except Exception:
                StreamEmitter = None
            if StreamEmitter is None:
                return
            self._emitter = StreamEmitter()
        try:
            elapsed_ms = int((time.monotonic() - t_start) * 1000)
            payload = {
                "stage": stage,
                "elapsed_ms": elapsed_ms,
                **extra,
            }
            self._emitter.emit(stage, payload)
        except Exception:
            pass

    def _start_heartbeat(self, t_total: float) -> None:
        """Launch a periodic heartbeat so the frontend knows SPEG is alive
        during long LLM/tool phases."""
        if self._emitter is None or self._heartbeat_interval_s <= 0:
            return

        async def _hb():
            try:
                while True:
                    await asyncio.sleep(self._heartbeat_interval_s)
                    if self._emitter is None:
                        return
                    try:
                        elapsed_ms = int((time.monotonic() - t_total) * 1000)
                        self._emitter.emit(HEARTBEAT, {
                            "stage": "alive",
                            "elapsed_ms": elapsed_ms,
                        })
                    except Exception:
                        pass
            except asyncio.CancelledError:
                return

        try:
            loop = asyncio.get_event_loop()
            self._heartbeat_task = loop.create_task(_hb())
        except RuntimeError:
            # No running loop in this context (e.g. called from sync code).
            self._heartbeat_task = None

    async def _stop_heartbeat(self) -> None:
        task = self._heartbeat_task
        self._heartbeat_task = None
        if task is None:
            return
        try:
            task.cancel()
            await asyncio.wait([task], timeout=0.2)
        except Exception:
            pass

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

        # P0: announce turn start so frontend logs the request.
        self._emit_stage(TURN_STARTED, t_total,
                         user_input_len=len(user_input or ""))
        # P1: heartbeat the moment we enter — covers all stages.
        self._start_heartbeat(t_total)

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
                raise ValueError(f"Budget: {budget_result.exceeded}")

            t_planner = time.monotonic()
            self._emit_stage(PLANNER_STARTED, t_total)
            plan_nodes = self._planner.plan(ctx)
            metrics.capture_planner((time.monotonic() - t_planner) * 1000)
            self._emit_stage(
                PLANNER_COMPLETED, t_total,
                plan_nodes=len(plan_nodes or []),
            )

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
                self._emit_stage(
                    GRAPH_COMPILED, t_total,
                    nodes=getattr(dag, "total_nodes", 0),
                    max_depth=getattr(dag, "max_depth", 0),
                )

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
                self._emit_stage(
                    STRUCTURAL_VALIDATED, t_total,
                    ok=bool(dag.is_valid),
                )

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
                    # Stage 6b: Pre-execution repair attempt
                    repair_label = "pre_execution_repair"
                    repair_span = self._trace.add_span(repair_label,
                        error_count=len(sem_result.errors))

                    self._emit_stage(
                        PRE_REPAIR_STARTED, t_total,
                        error_count=len(sem_result.errors),
                    )

                    repair_result = self._pre_exec_repair.try_repair(dag, sem_result.errors)

                    self._emit_stage(
                        PRE_REPAIR_COMPLETED, t_total,
                        repaired=bool(repair_result.repaired),
                        repaired_count=sum(
                            1 for ev in (repair_result.repair_events or [])
                            if getattr(ev, "repaired", False)
                        ),
                    )

                    if repair_result.repaired:
                        # Re-validate with repaired DAG
                        sem_result2 = self._sem_validator.validate(dag)
                        if sem_result2.valid:
                            repair_span.stop(status="ok", error_code="repaired")
                            repair_events_data = [
                                {
                                    "node_id": e.node_id,
                                    "original_action": e.original_action,
                                    "normalized_action": e.normalized_action,
                                    "operation": e.operation,
                                    # v3.10: surface which alias source
                                    # the rewrite came from. ``"canonical"``
                                    # means action_alias.resolve_action_alias
                                    # handled it; ``"extended"`` means the
                                    # pre_execution_repair runtime fallback
                                    # was the only thing that knew this
                                    # alias.
                                    "source": getattr(e, "source", "none"),
                                    "validation_before": e.validation_error_code_before,
                                    "validation_after": e.validation_after,
                                }
                                for e in repair_result.repair_events if e.repaired
                            ]
                            ctx.extras["pre_exec_repair_events"] = repair_events_data
                            ctx.extras["pre_exec_repair_applied"] = True
                            risk_level = sem_result2.risk_level
                        else:
                            # Repair applied but still invalid → try LLM replan
                            repair_span.stop(status="partial", error_code="still_invalid")
                            llm_repaired = await self._try_llm_replan(
                                ctx, budget, sem_result2, metrics
                            )
                            if llm_repaired:
                                repair_span._span.metadata["llm_replan"] = True
                                dag = llm_repaired
                                # Re-validate AGAIN
                                sem_result3 = self._sem_validator.validate(dag)
                                if sem_result3.valid:
                                    risk_level = sem_result3.risk_level
                                else:
                                    # Still failing → structured error
                                    repair_span.stop(status="error", error_code="unrepairable")
                                    for e in sem_result3.errors:
                                        errors.append(build_error(
                                            e.code, e.message,
                                            stage="semantic_validate", node_id=e.node_id,
                                        ))
                                    return self._build_result(ctx, dag, node_results, final_response,
                                        errors, metrics, budget, t_total, sem_result3.risk_level, approval_required)
                            else:
                                for e in sem_result2.errors:
                                    errors.append(build_error(
                                        e.code, e.message,
                                        stage="semantic_validate", node_id=e.node_id,
                                    ))
                                return self._build_result(ctx, dag, node_results, final_response,
                                    errors, metrics, budget, t_total, sem_result.risk_level, approval_required)
                    else:
                        # Cannot repair — check if LLM replan is possible
                        repair_span.stop(status="error", error_code="unrepairable")
                        llm_remaining = self._config.max_llm_calls - budget.llm_calls
                        if self._pre_exec_repair.should_replan_with_llm(repair_result, llm_remaining):
                            llm_repaired = await self._try_llm_replan(
                                ctx, budget, sem_result, metrics
                            )
                            if llm_repaired:
                                repair_span._span.metadata["llm_replan"] = True
                                dag = llm_repaired
                                sem_result2 = self._sem_validator.validate(dag)
                                if sem_result2.valid:
                                    risk_level = sem_result2.risk_level
                                else:
                                    for e in sem_result2.errors:
                                        errors.append(build_error(
                                            e.code, e.message,
                                            stage="semantic_validate", node_id=e.node_id,
                                        ))
                                    return self._build_result(ctx, dag, node_results, final_response,
                                        errors, metrics, budget, t_total, sem_result2.risk_level, approval_required)
                            else:
                                for e in sem_result.errors:
                                    errors.append(build_error(
                                        e.code, e.message,
                                        stage="semantic_validate", node_id=e.node_id,
                                    ))
                                return self._build_result(ctx, dag, node_results, final_response,
                                    errors, metrics, budget, t_total, sem_result.risk_level, approval_required)
                        else:
                            # Unrepairable, no LLM budget → fail
                            unrepairable_reason = repair_result.unrepairable_reason or "errors not repairable"
                            errors.append(build_error(
                                "UNREPAIRABLE",
                                f"Validation errors could not be repaired: {unrepairable_reason}. "
                                f"Repair attempts: {repair_result.repair_attempts}",
                                stage="pre_execution_repair",
                            ))
                            return self._build_result(ctx, dag, node_results, final_response,
                                errors, metrics, budget, t_total, sem_result.risk_level, approval_required)
                else:
                    risk_level = sem_result.risk_level
                self._emit_stage(
                    SEMANTIC_VALIDATED, t_total,
                    risk_level=risk_level,
                )

                # Stage 7: Risk policy check
                risk_assessment = self._risk_policy.assess(dag)
                risk_level = risk_assessment.risk_level
                self._emit_stage(
                    RISK_ASSESSED, t_total,
                    risk_level=risk_assessment.risk_level,
                    safe_to_run=bool(risk_assessment.safe_to_run),
                )
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

                self._emit_stage(
                    EXECUTION_STARTED, t_total,
                    nodes=dag.total_nodes,
                )
                node_results = await self._scheduled_execute(dag, ctx, budget)
                execution_ms = (time.monotonic() - t_exec) * 1000
                execution_span.stop()
                metrics.capture_execution(execution_ms, node_results, dag)
                ok = sum(1 for n in node_results.values() if n.success)
                fail = sum(1 for n in node_results.values() if not n.success)
                self._emit_stage(
                    EXECUTION_COMPLETED, t_total,
                    ok=ok,
                    fail=fail,
                    total=len(node_results),
                )

                # Stage 10: Repair if needed
                repair_spans = []
                for node in dag.nodes:
                    result = node_results.get(node.id)
                    if result and not result.success:
                        repair = self._repair.assess(node, result, dag)
                        if repair.strategy == "retry":
                            self._emit_stage(
                                REPAIR_ATTEMPT, t_total,
                                node_id=node.id,
                            )
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
                self._emit_stage(
                    MERGE_COMPLETED, t_total,
                    nodes=merged.get("total_nodes", 0),
                    ok=merged.get("success_count", 0),
                )

                # Stage 13: Finalizer (optional 1 LLM call)
                self._emit_stage(FINALIZING_STARTED, t_total)
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
                self._emit_stage(FINALIZING_COMPLETED, t_total)

            metrics.set_llm_calls(budget.llm_calls)
            metrics.set_risk_level(risk_level)
            self._emit_stage(TURN_COMPLETED, t_total)

            result = self._build_result(
                ctx, dag, node_results, final_response,
                errors, metrics, budget, t_total, risk_level, approval_required,
                rollback_plan,
            )
            return result

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
        finally:
            await self._stop_heartbeat()

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
    # LLM-based replanning for pre-execution repair
    # ========================================================================

    async def _try_llm_replan(self, ctx, budget, sem_result, metrics):
        """Attempt LLM-based replanning when deterministic repair fails.

        Requires: budget.llm_calls < max_llm_calls and hasn't exceeded planner budget.

        Returns:
            New ExecutionDAG if successful, None otherwise.
        """
        from .graph_compiler import GraphCompiler

        llm_budget = budget.check_llm_call()
        if not llm_budget.ok:
            return None

        planner_budget = budget.check_planner()
        if not planner_budget.ok:
            return None

        self._pre_exec_repair.mark_llm_repair_attempt()

        try:
            # Re-plan with error context
            error_summary = "; ".join(e.message[:100] for e in sem_result.errors[:3])
            contextualized_input = (
                f"{ctx.user_input}\n\n"
                f"[PREVIOUS PLAN HAD ERRORS: {error_summary}. "
                f"Please fix the action names and tool references to match canonical contracts.]"
            )
            ctx.user_input = contextualized_input

            t_plan = time.time()
            plan_nodes = self._planner.plan(ctx)
            metrics.capture_planner((time.time() - t_plan) * 1000)

            dag = self._compiler.compile(plan_nodes)
            return dag
        except Exception:
            return None

    # ========================================================================
    # Audit: mark blocked nodes for audit logging
    # ========================================================================

    def _mark_blocked_nodes_for_audit(self, dag, node_results, errors):
        """Ensure blocked/failed nodes are tracked in audit."""
        if dag is None:
            return
        for node in dag.nodes:
            if node.status == ExecutionStatus.PENDING:
                if not node.error:
                    node.status = ExecutionStatus.SKIPPED
                    node.error = "Blocked by policy or validation error"

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

        # v3.10: collect alias provenance so the SPEGResult surface
        # can show planner terminology drift at a glance (audit /
        # trace surfaces keep the raw bookkeeping; we just propagate
        # the per-node summary through metadata).
        alias_drift_summary = []
        if dag:
            for nd in dag.nodes:
                if nd.action_normalized_from_alias:
                    alias_drift_summary.append({
                        "node_id": nd.id,
                        "action_original": nd.action_original,
                        "action_normalized": nd.args.get("action", ""),
                    })
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
                "alias_normalizations": alias_drift_summary,
                "pre_exec_repair_events": ctx.extras.get("pre_exec_repair_events", []),
                "pre_exec_repair_applied": ctx.extras.get("pre_exec_repair_applied", False),
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
