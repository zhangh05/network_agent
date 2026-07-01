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
from .plan_enrichment import enrich_dag_from_user_request
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
        extras: dict[str, Any] | None = None,
    ) -> SPEGResult:
        """Execute a single user request through the bank-grade pipeline.

        Args:
            extras: caller-supplied metadata map that lands in
                ``ctx.extras``.  Used for approval bypass
                (``approved_risk=True``) and other caller signals.
        """
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
            extras=dict(extras or {}),
        )

        errors: list[SPEGError] = []
        node_results: dict[str, ToolResult] = {}
        final_response = ""
        dag = None
        risk_level = "low"
        approval_required = False
        rollback_plan = None

        # ── v3.11: Fast-path classifier ───────────────────────────────
        # Simple greetings / definition questions skip the planner
        # and go straight to a direct-answer LLM call.  This cuts
        # first_answer_token_ms dramatically and avoids burning
        # an LLM call just to say "I don't need any tools."
        from .fast_path import classify_direct_answer

        fast = classify_direct_answer(user_input)
        if fast.enabled:
            self._emit_stage(FINALIZING_STARTED, t_total)
            direct_latency_start = time.monotonic()
            try:
                direct_resp = await self._generate_direct_answer(
                    ctx.user_input, budget
                )
                final_response = (direct_resp or "").strip()
            except Exception:
                final_response = "收到。"
            direct_answer_latency_ms = (
                time.monotonic() - direct_latency_start
            ) * 1000

            self._emit_stage(FINALIZING_COMPLETED, t_total)
            self._emit_stage(TURN_COMPLETED, t_total)

            metrics.capture_finalizer(direct_answer_latency_ms)
            metrics.set_llm_calls(budget.llm_calls or 1)

            return self._build_result(
                ctx, None, node_results, final_response,
                errors, metrics, budget, t_total, "low", False,
                extra={
                    "fast_path": True,
                    "route": fast.route,
                    "planner_skipped": True,
                    "used_tools": False,
                    "direct_answer_latency_ms": direct_answer_latency_ms,
                    "skip_reason": fast.reason,
                },
            )

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
                enrichment_events = enrich_dag_from_user_request(dag, ctx.user_input)
                if enrichment_events:
                    ctx.extras["plan_enrichment_events"] = [
                        {
                            "node_id": ev.node_id,
                            "tool": ev.tool,
                            "field": ev.field,
                            "value": ev.value,
                            "reason": ev.reason,
                        }
                        for ev in enrichment_events
                    ]
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
                    hard_block=bool(risk_assessment.hard_block),
                    requires_approval=bool(risk_assessment.requires_approval),
                )

                # v3.12: three-way risk gate.
                #  1. hard_block → fail immediately (no override).
                #  2. approval_required (not hard_block) → return with
                #     approval metadata so the frontend shows a bubble.
                #  3. safe → continue execution.
                if risk_assessment.hard_block:
                    errors.append(build_error(
                        SpegErrorCode.RISK_CRITICAL_DENIED,
                        risk_assessment.blocked_reason,
                        stage="risk_policy",
                    ))
                    return self._build_result(
                        ctx, dag, node_results, final_response,
                        errors, metrics, budget, t_total,
                        risk_level,
                        approval_required=True,
                        extra={
                            "hard_block": True,
                            "blocked_reason": risk_assessment.blocked_reason,
                            "blocked_nodes": risk_assessment.blocked_nodes,
                        },
                    )

                if risk_assessment.requires_approval:
                    # Check if user already approved via metadata
                    approved = self._check_approval_bypass(ctx)
                    if not approved:
                        # Return with approval metadata — caller
                        # (AgentResult → frontend) should surface the
                        # approval bubble.
                        self._emit_stage(TURN_COMPLETED, t_total)
                        metrics.set_llm_calls(budget.llm_calls)
                        metrics.set_risk_level(risk_level)
                        return self._build_result(
                            ctx, dag, node_results, final_response,
                            errors, metrics, budget, t_total,
                            risk_level,
                            approval_required=True,
                            extra={
                                "approval_required": True,
                                "approval_reason": risk_assessment.approval_reason,
                                "approval_nodes": risk_assessment.approval_nodes,
                                "approval_details": risk_assessment.approval_details,
                                "risk_level": risk_level,
                                "command_summary": _summarize_commands(dag),
                                "tool_summary": _summarize_tools(dag),
                                "warnings": risk_assessment.warnings,
                            },
                        )

                approval_required = (
                    risk_assessment.requires_approval and
                    not self._check_approval_bypass(ctx)
                )

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

                # Stage 10: Tool retry summary. v3.10: the actual
                # retry decision is made during _scheduled_execute
                # (per-node, in-layer) — this stage is now a
                # summary aggregator, not a re-retry. We collect
                # the policy decisions stashed on each node,
                # surface them to trace / audit / SPEGResult
                # metadata, and emit the ``tool_retry`` event.
                from .tool_retry_policy import RetryDecision
                retry_events: list[dict] = []
                retry_summary: dict = {
                    "retry_attempts": 0,
                    "retried_nodes": [],
                    "retry_succeeded": 0,
                    "retry_failed": 0,
                    "retry_blocked": 0,
                }
                for node in dag.nodes:
                    decision = getattr(node, "last_retry_decision", None)
                    if decision is None or not isinstance(
                        decision, RetryDecision
                    ):
                        continue
                    result = node_results.get(node.id)
                    outcome_ok = bool(result and result.success)
                    ev = {
                        "type": "tool_retry",
                        "node_id": node.id,
                        "tool_id": node.tool,
                        "attempt": decision.retry_count,
                        "max_retries": decision.max_retries,
                        "error_code": decision.error_code,
                        "original_error": decision.notes.get(
                            "original_error", ""
                        ),
                        "retry_allowed": decision.retry_allowed,
                        "reason": decision.reason,
                        "backoff_ms": decision.backoff_ms,
                        "idempotent": decision.idempotent,
                        "side_effect": decision.side_effect,
                        "blocked_by_policy": decision.blocked_by_policy,
                        "final_status": (
                            "succeeded" if outcome_ok
                            else "failed" if decision.retry_allowed
                            else "blocked"
                        ),
                        "duration_ms": (
                            float(result.latency_ms) if result else 0.0
                        ),
                    }
                    retry_events.append(ev)
                    if decision.retry_allowed:
                        retry_summary["retry_attempts"] += 1
                        retry_summary["retried_nodes"].append(node.id)
                        if outcome_ok:
                            retry_summary["retry_succeeded"] += 1
                        else:
                            retry_summary["retry_failed"] += 1
                    elif decision.blocked_by_policy:
                        retry_summary["retry_blocked"] += 1
                ctx.extras["retry_summary"] = retry_summary
                ctx.extras["retry_events"] = retry_events

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
        """Execute DAG layer by layer with ResourceScheduler concurrency control.

        v3.10 (tool retry): each node in a deeper layer is gated by
        its dep status. If any upstream is FAILED or SKIPPED, the
        node is marked ``skipped`` with reason ``dependency_failed``
        and the tool handler is NOT invoked.

        Failed nodes consult ``should_retry_tool_failure`` from
        :mod:`speg_engine.tool_retry_policy`. The policy is the
        single source of truth — both this path and the stage-10
        repair path route through it. We do NOT re-run the layer
        on a failed node; we re-invoke just the failed node's
        handler (if the policy allows it).
        """
        from .contracts import get_contract
        from .tool_retry_policy import should_retry_tool_failure
        from .execution_engine import _dependency_skip_reason

        all_results: dict[str, ToolResult] = {}
        active_global = 0

        for depth in range(dag.max_depth + 1):
            layer_nodes = dag.get_layer(depth)
            if not layer_nodes:
                continue

            # v3.10: dependency gate. A node whose deps failed or
            # were skipped is marked SKIPPED here, not run.
            ready: list = []
            for node in layer_nodes:
                skip_reason = _dependency_skip_reason(node, all_results)
                if skip_reason is not None:
                    skip_result = ToolResult(
                        node_id=node.id,
                        tool=node.tool,
                        success=False,
                        error=skip_reason,
                        error_code="DEPENDENCY_FAILED",
                        metadata={"skip_reason": "dependency_failed"},
                    )
                    node.status = ExecutionStatus.SKIPPED
                    node.error = skip_reason
                    node.result = None
                    node.finished_at = time.monotonic()
                    all_results[node.id] = skip_result
                    continue
                ready.append(node)
                node.status = ExecutionStatus.PENDING

            if not ready:
                continue

            # Schedule: apply concurrency limits.
            scheduled = self._scheduler.schedule_layer(ready, active_global)
            if not scheduled:
                scheduled = ready

            # Mark running
            for node in scheduled:
                node.status = ExecutionStatus.RUNNING
                node.started_at = time.monotonic()

            active_global += len(scheduled)
            layer_results = await self._tool_runtime.execute_layer(
                scheduled, ctx, all_results
            )
            active_global -= len(scheduled)

            # Process results — including v3.10 retry on failure.
            for node in scheduled:
                result = layer_results.get(node.id)
                if result is None:
                    result = ToolResult(
                        node_id=node.id,
                        tool=node.tool,
                        success=False,
                        error="No result returned from execution",
                        error_code="TOOL_EXCEPTION",
                    )

                if not result.success:
                    result = await self._handle_tool_failure(
                        node=node,
                        ctx=ctx,
                        all_results=all_results,
                        original_result=result,
                        budget=budget,
                        contract=get_contract(node.tool),
                        policy=should_retry_tool_failure,
                    )

                node.result = result.data
                node.error = result.error
                node.status = (
                    ExecutionStatus.SUCCESS if result.success
                    else ExecutionStatus.FAILED
                )
                node.latency_ms = result.latency_ms
                node.finished_at = time.monotonic()
                all_results[node.id] = result

            # Budget check between layers
            b = budget.check_execution()
            if not b.ok:
                break

        return all_results

    async def _handle_tool_failure(
        self,
        *,
        node,
        ctx,
        all_results: dict,
        original_result: ToolResult,
        budget: BudgetController,
        contract,
        policy,
    ) -> ToolResult:
        """Single-source-of-truth retry path. Mirrors
        ``ExecutionEngine._handle_failure`` but additionally
        enforces the per-request budget before invoking the policy.
        """
        # Best-effort: infer the error code if the handler did not
        # set one explicitly.
        error_code = (original_result.error_code or "").strip().upper()
        if not error_code:
            err = (original_result.error or "").lower()
            if "timeout" in err or "timed out" in err:
                error_code = "TOOL_TIMEOUT"
            elif "rate" in err and "limit" in err:
                error_code = "RATE_LIMITED"
            elif "connection" in err and "reset" in err:
                error_code = "CONNECTION_RESET"
            else:
                error_code = "TOOL_EXCEPTION"

        # Budget gate. The retry duration would push us past the
        # per-request / per-tool ceiling — refuse.
        budget_status = budget.check_execution()
        budget_ok = bool(budget_status.ok)

        decision = policy(
            node=node,
            tool_contract=contract,
            error_code=error_code,
            error_message=original_result.error or "",
            config_max_retries=(
                int(getattr(contract, "max_retries", 0) or 0)
                if contract is not None else 0
            ),
            global_max_retries_per_node=self._config.max_retries_per_node,
            budget_ok=budget_ok,
        )

        # Stash the decision for the audit / metadata aggregator.
        node.last_retry_decision = decision

        if not decision.retry_allowed:
            return original_result

        # Backoff before the second attempt.
        await asyncio.sleep(decision.backoff_ms / 1000.0)
        node.retry_count += 1
        node.status = ExecutionStatus.RETRYING

        retry_result = await self._tool_runtime.execute_node(
            node, ctx, all_results
        )
        retry_result.retry_count = node.retry_count

        # Annotate the ToolResult with retry provenance.
        retry_result.metadata = dict(retry_result.metadata or {})
        retry_result.metadata["retried"] = True
        retry_result.metadata["retry_count"] = node.retry_count
        retry_result.metadata["retry_reason"] = decision.reason
        retry_result.metadata["retry_backoff_ms"] = decision.backoff_ms
        retry_result.metadata["retry_error_code"] = decision.error_code
        retry_result.metadata["retry_original_error"] = (
            decision.notes.get("original_error", "")
        )

        if retry_result.success:
            return retry_result
        return retry_result

    # ========================================================================
    # Direct answer (fast path)
    # ========================================================================

    async def _generate_direct_answer(
        self, user_input: str, budget: BudgetController
    ) -> str:
        """Generate a direct answer without tools or JSON planning.

        The call is streamed to the user (stream_to_user=True,
        stream_scope='direct_answer') so first_answer_token is
        measured from the actual answer token.
        """
        llm_budget = budget.check_llm_call()
        if not llm_budget.ok:
            return "收到。"

        system_msg = (
            "你是网络工程助手。直接回答用户问题。"
            "不要调用工具。不要输出 JSON。"
            "不要编造已执行的检查结果。"
        )
        result = self._llm_invoke(
            system=system_msg,
            user=user_input,
            extra={
                "runtime_engine": "speg",
                "stream_scope": "direct_answer",
                "stream_to_user": True,
            },
        )
        if isinstance(result, str):
            return result
        # LLMResponse object
        return getattr(result, "content", str(result))

    def _check_approval_bypass(self, ctx: StatelessContext) -> bool:
        """Check if the current request has been pre-approved by the user.

        When the frontend shows an approval bubble and the user clicks
        "approve", the same request is re-submitted with
        ``ctx.extras["approved_risk"] = True``.  This gate lets the
        approved request skip the approval_required barrier while
        keeping the hard_block gate intact.
        """
        return bool(ctx.extras.get("approved_risk") or False)

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
        extra: dict[str, Any] | None = None,
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

        # v3.11: merge fast-path metadata tags when present.
        base_meta = {
            "fast_path": False,
            "route": "",
            "planner_skipped": False,
            "used_tools": len(node_results) > 0,
            "direct_answer_latency_ms": 0.0,
            # v3.12: approval tracking
            "approval_required": False,
            "hard_block": False,
            "approval_reason": "",
            "approval_nodes": [],
            "approval_details": [],
            "command_summary": [],
            "tool_summary": [],
        }
        if extra:
            base_meta.update(extra)

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
                **base_meta,
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
                "plan_enrichment_events": ctx.extras.get("plan_enrichment_events", []),
                "pre_exec_repair_events": ctx.extras.get("pre_exec_repair_events", []),
                "pre_exec_repair_applied": ctx.extras.get("pre_exec_repair_applied", False),
                # v3.10 (tool retry): aggregate per-node retry decisions
                # collected by stage 10. ``retry_summary`` is a small
                # dict (counts); ``retry_events`` is the full list of
                # ``tool_retry`` events for audit.
                "retry_summary": ctx.extras.get("retry_summary", {
                    "retry_attempts": 0,
                    "retried_nodes": [],
                    "retry_succeeded": 0,
                    "retry_failed": 0,
                    "retry_blocked": 0,
                }),
                "retry_events": ctx.extras.get("retry_events", []),
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


# ========================================================================
# Module-level helpers (used by engine.py and risk_policy)
# ========================================================================

def _summarize_commands(dag) -> list[dict[str, str]]:
    """Extract exec.run command summaries for the approval bubble."""
    if dag is None:
        return []
    commands = []
    for node in dag.nodes:
        if node.tool != "exec.run":
            continue
        cmd = str(node.args.get("command", "")[:200])
        if cmd:
            commands.append({"node_id": node.id, "command": cmd})
    return commands


def _summarize_tools(dag) -> list[str]:
    """List distinct tool IDs in the DAG for the approval bubble."""
    if dag is None:
        return []
    seen = {}
    for node in dag.nodes:
        seen[node.tool] = seen.get(node.tool, 0) + 1
    return [f"{tid} (x{count})" if count > 1 else tid
            for tid, count in sorted(seen.items())]
