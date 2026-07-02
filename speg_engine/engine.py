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
from .fast_path import _build_conversation_history_block
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
from .runtime_contracts import ExecutionContract, ExecutionObligationViolation
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
        self._risk_policy = RiskPolicyEngine(self._config)
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

        # ── v4.2: self-healing contract validation ─────────
        from .runtime_contracts import ContractValidator, ContractDegradation
        c_validator = ContractValidator(ExecutionContract)
        contract_report = c_validator.validate_all()

        if contract_report.has_critical_failure():
            errors.append(build_error(
                "CONTRACT_VIOLATION",
                f"Critical contract checks failed: "
                + "; ".join(
                    c.name for c in contract_report.checks
                    if c.level == ContractDegradation.HARD
                ),
                stage="engine",
                risk_level="high",
            ))
            return self._build_result(
                ctx, None, node_results, final_response,
                errors, metrics, budget, t_total,
                risk_level="high", approval_required=False,
                extra={"contract_report": contract_report},
            )
        ctx.extras["contract_report"] = contract_report

        errors: list[SPEGError] = []
        node_results: dict[str, ToolResult] = {}
        final_response = ""
        dag = None
        risk_level = "low"
        approval_required = False
        rollback_plan = None

        # ── v3.11: Fast-path classifier ───────────────────────────────
        # Simple greetings / definition questions skip the planner
        # and go to a direct-answer LLM call.  This cuts
        # first_answer_token_ms dramatically and avoids burning
        # an LLM call just to say "I don't need any tools."
        #
        # v3.13: conversation-ref queries ("什么意思", "我上句话说了什么"
        # etc.) inject session.history into the direct-answer prompt so
        # the LLM can reference the previous turn.  conversation-ref
        # patterns that do NOT match the narrow classifier are still
        # fast-pathed when history is available — they're clearly not
        # tool requests and the planner would waste an LLM call.
        from .fast_path import (
            classify_direct_answer,
            is_conversation_ref,
            FastPathDecision,
        )

        fast = classify_direct_answer(user_input)
        conv_ctx = ctx.extras.get("conversation_context")
        conv_history = getattr(conv_ctx, "recent_messages", None) or []
        is_conv_ref = bool(is_conversation_ref(user_input) and conv_history)

        # ── v3.14: task-intent override for fast path ────────────
        # If the input has task-intent verbs but the narrow classifier
        # still matched (e.g. "分析这个是什么问题" matches "是什么"),
        # force full SPEG so the planner can produce tool nodes.
        task_intent = detect_task_intent(user_input)
        if task_intent.is_task and task_intent.requires_tool_likely and fast.enabled:
            fast = FastPathDecision(
                enabled=False, route="",
                reason=f"task_intent_override: {task_intent.intent_type}",
            )

        # v3.13: conversation-ref with history → force fast-path.
        # These queries ("我上句话说了什么", "我说了什么") are clearly
        # not tool requests and the planner would waste a call.  We
        # route them through direct-answer with history injected.
        if is_conv_ref and not fast.enabled:
            fast = FastPathDecision(
                enabled=True, route="conversation_ref",
                reason="conversation-ref with history available",
            )

        if fast.enabled:
            self._emit_stage(FINALIZING_STARTED, t_total)
            direct_latency_start = time.monotonic()

            try:
                direct_resp = await self._generate_direct_answer(
                    ctx.user_input, budget,
                    conversation_context=conv_ctx if is_conv_ref else None,
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
                    "conversation_ref": is_conv_ref,
                    "conversation_history_used": bool(conv_history and is_conv_ref),
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

            # v4.1: pre-set task_intent so PlanSchema.validate_raw
            # can enforce ExecutionObligationViolation for empty
            # plans on task requests.
            task_intent = detect_task_intent(ctx.user_input)
            ctx.extras["task_intent_is_task"] = task_intent.is_task

            # ── v4: planner fail-fast ──────────────────────────────
            # ``ExecutionObligationViolation`` is raised by the
            # planner when the user request requires execution but
            # the LLM produced an empty graph. Catch it and
            # produce a structured error result — same code path
            # as the v3.14 empty-plan task-intent guard, just
            # reached via raise instead of in-engine check.
            try:
                plan_nodes = self._planner.plan(ctx)
            except ExecutionObligationViolation as exc:
                metrics.capture_planner(
                    (time.monotonic() - t_planner) * 1000
                )
                errors.append(build_error(
                    SpegErrorCode.PLANNER_EMPTY_FOR_TASK_INTENT,
                    f"Planner failed execution-obligation check: {exc}",
                    stage="planner",
                    risk_level="high",
                ))
                return self._build_result(
                    ctx, None, node_results, final_response,
                    errors, metrics, budget, t_total,
                    risk_level="high", approval_required=False,
                )
            metrics.capture_planner((time.monotonic() - t_planner) * 1000)
            self._emit_stage(
                PLANNER_COMPLETED, t_total,
                plan_nodes=len(plan_nodes or []),
            )

            # v4.1: planner output has been schema-validated by
            # PlanSchema.validate_raw() inside Planner.plan().
            ctx.extras["plan_schema_validated"] = True

            if not plan_nodes:
                # ── v3.14: empty-plan task-intent guard ─────────────
                # If the user asked for a clear task (analyse, inspect,
                # read, diagnose, etc.) but the planner produced no
                # nodes, this is a planner failure — not a "nothing to
                # do" scenario.
                if plan_nodes_empty_for_task(ctx.user_input):
                    errors.append(build_error(
                        SpegErrorCode.PLANNER_EMPTY_FOR_TASK_INTENT,
                        "Planner returned empty nodes for a task-intent request. "
                        "The system cannot complete the requested analysis.",
                        stage="planner",
                        risk_level="high",
                    ))
                    return self._build_result(
                        ctx, None, node_results, final_response,
                        errors, metrics, budget, t_total,
                        risk_level="high", approval_required=False,
                    )

                # No tools — skip to finalizer
                t_merge = time.monotonic()
                # v6: causal order is still valid even without tool execution
                ctx.extras.setdefault("causal_order_valid", True)
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

                # v4.1: after execution, every node must have a
                # terminal status (SUCCESS / FAILED / SKIPPED).
                if dag and dag.nodes:
                    for n in dag.nodes:
                        assert n.status in (
                            ExecutionStatus.SUCCESS,
                            ExecutionStatus.FAILED,
                            ExecutionStatus.SKIPPED,
                        ), f"node {n.id} is still {n.status.value} after execution"

                # v4.1: context was built with causal ordering
                # (causal_index, not created_at).
                ctx.extras["causal_order_valid"] = True

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

                # ── v3.14: Final-response validation ────────────────
                # After the finalizer, check whether the response
                # actually completes a task-intent request.  Uses
                # the structured validator that avoids false positives
                # on real analysis output.
                vresult = validate_final_response(ctx.user_input, final_response)
                if not vresult.valid:
                    # Attempt one finalizer retry with stronger prompt
                    retry_ok = False
                    if (
                        self._config.enable_finalizer
                        and (budget.llm_calls < self._config.max_llm_calls)
                    ):
                        llm_budget_retry = budget.check_llm_call()
                        if llm_budget_retry.ok:
                            self._emit_stage(FINALIZING_STARTED, t_total)
                            try:
                                final_response = await self._finalizer.finalize(
                                    ctx, merged, is_retry=True,
                                )
                                retry_ok = True
                            except Exception:
                                pass
                            self._emit_stage(FINALIZING_COMPLETED, t_total)

                            if retry_ok:
                                vresult2 = validate_final_response(
                                    ctx.user_input, final_response,
                                )
                                retry_ok = vresult2.valid

                    if not retry_ok:
                        errors.append(build_error(
                            SpegErrorCode.FINALIZER_TASK_INCOMPLETE,
                            f"Finalizer produced an incomplete response "
                            f"('{final_response[:80]}') for a task-intent request. "
                            f"Tools executed but no analysis conclusion was generated.",
                            stage="finalizer",
                            risk_level="high",
                        ))

            metrics.set_llm_calls(budget.llm_calls)
            metrics.set_risk_level(risk_level)
            self._emit_stage(TURN_COMPLETED, t_total)

            result = self._build_result(
                ctx, dag, node_results, final_response,
                errors, metrics, budget, t_total, risk_level, approval_required,
                rollback_plan,
            )

            # ── v6: final convergence gate ──────────────────────
            from .runtime_contracts import ExecutionSemanticsContract
            if ExecutionSemanticsContract.SINGLE_TRUTH_TOOL_RESULT:
                _v6_validate_tool_truth(node_results)
            if ExecutionSemanticsContract.CAUSAL_ORDER_STRICT:
                _v6_validate_causal_order(ctx)
            if ExecutionSemanticsContract.SCHEMA_EXECUTION_UNIFIED:
                _v6_validate_plan_consistency(ctx)

            # ── Ultimate Stability Gate ─────────────────────────
            from .runtime_stability import (
                IssueCollector, Severity, IssueCategory,
                SystemUnstableError, SYSTEM_MODE,
                system_acceptance_check,
            )
            collector = IssueCollector()
            _collect_stability_issues(ctx, result, errors, collector)

            if not system_acceptance_check(collector, mode=SYSTEM_MODE):
                raise SystemUnstableError(collector)

            result.metadata["stability_report"] = collector.to_dict()

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
        self,
        user_input: str,
        budget: BudgetController,
        conversation_context: Any | None = None,
    ) -> str:
        """Generate a direct answer without tools or JSON planning.

        The call is streamed to the user (stream_to_user=True,
        stream_scope='direct_answer') so first_answer_token is
        measured from the actual answer token.

        v3.14: accepts a full ``ConversationContext`` (with
        token-budgeted recent turns, session_summary, and
        retrieved_history) instead of just the flat chat list.
        """
        llm_budget = budget.check_llm_call()
        if not llm_budget.ok:
            return "收到。"

        context_block = ""
        if conversation_context is not None:
            try:
                context_block = conversation_context.format_for_prompt()
            except Exception:
                context_block = ""

        system_msg = (
            "你是网络工程助手。直接回答用户问题。"
            "不要调用工具。不要输出 JSON。"
            "不要编造已执行的检查结果。"
        )
        if context_block:
            system_msg += f"\n\n{context_block}\n\n"
            system_msg += (
                "如果用户问的是关于之前对话的问题（如'什么意思'、'我刚才说了什么'），"
                "请基于上述对话历史回答。"
                "不要说'我无法查看之前的对话'或'缺少上下文'——对话历史已经提供给你了。"
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
            # v3.13: conversation context
            "conversation_ref": False,
            "conversation_history_used": False,
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


# ── v3.14: Task-intent detection ─────────────────────────────────────────

_TASK_INTENT_VERBS = (
    # Explicit action verbs
    "读取", "分析", "巡检", "检查", "生成",
    "总结", "排查", "对比", "诊断", "判断",
    "监测", "追踪", "绘制", "统计", "汇报",
    "评估", "审查", "核实", "校验", "整理",
    "执行", "处理", "导出", "保存",
    # Visual/file reference patterns
    "看这个文件", "看这个截图", "看这个报文", "看这个日志", "看这个配置",
    "看看这个", "看下这个", "查看这个",
    # Task-completion patterns
    "帮我看看", "帮我看下", "分析一下",
    "给出结论", "给出原因", "处理建议", "建议怎么",
    # Report patterns
    "生成报告", "导出结果", "保存分析",
)

# Patterns that make a definition question NOT task intent.
_Q_DEFINITION_PATTERNS = ("是什么", "什么是", "什么叫", "的定义", "介绍一下")

# Patterns that make a "是什么"-containing query STILL task intent.
_Q_TASK_OVERRIDES = (
    "帮我分析", "分析一下", "看这个", "看看这个",
    "这个截图", "这个报文", "这个日志", "这个文件",
    "读取", "检查一下", "排查", "是什么原因", "是什么问题",
    "为什么会这样", "什么异常", "什么错误",
)

_TASK_INTENT_RESULT_FIELDS = ("结论", "发现", "原因", "建议", "异常",
                              "正常", "风险", "下一步", "依据", "诊断")

# Task-verb-to-recommended-tool mapping for deterministic route fallback.
_TASK_TO_DEFAULT_TOOL = {
    "inspection": "inspection.manage",
    "file_read_analysis": "workspace.file",
    "artifact_read_analysis": "workspace.artifact",
    "pcap_analysis": "pcap.manage",
    "config_analysis": "config.manage",
    "command_check": "exec.run",
    "text_analysis": "text.analyze",
    "report": "data.manage",
}


class TaskIntentResult:
    """Structured task-intent detection result."""
    is_task: bool = False
    intent_type: str = ""       # analysis / inspection / file_read_analysis / ...
    evidence: list[str] = None
    requires_tool_likely: bool = False

    def __post_init__(self):
        if self.evidence is None:
            self.evidence = []

    @property
    def requires_execution(self) -> bool:
        """v4 contract alias: the user request requires the
        runtime to produce a real execution (tool calls / DAG).

        Defaults to ``requires_tool_likely``; subclasses or
        specialised detectors can override to combine multiple
        signals (e.g. ``is_task and intent_type != 'definition'``).
        The v4 ``enforce_execution_obligation`` guard reads this
        property name, so the planner / engine / tests all
        share a single vocabulary.
        """
        return bool(self.requires_tool_likely)


def detect_task_intent(user_input: str) -> TaskIntentResult:
    """Unified task-intent detector.

    Returns a structured TaskIntentResult with:
      - is_task: whether this is a task-type request
      - intent_type: classification (analysis, inspection, etc.)
      - evidence: which rules matched
      - requires_tool_likely: whether tools are probably needed

    Rules (in priority order):
      1. Definition questions ("是什么", "什么是") → NOT task
         UNLESS the query also contains task-override patterns.
      2. Task verbs → task intent.
      3. Visual/file reference → task intent.
      4. Report/generation → task intent.
      5. Otherwise → not task intent.
    """
    text = (user_input or "").strip()
    result = TaskIntentResult()
    if not text:
        return result

    # Step 1: Check for definition patterns
    has_def = any(p in text for p in _Q_DEFINITION_PATTERNS)
    has_override = any(p in text for p in _Q_TASK_OVERRIDES)

    if has_def and not has_override:
        return result  # Pure definition → not task

    # Step 2: Check for task verbs and patterns
    matched = [v for v in _TASK_INTENT_VERBS if v in text]
    if matched:
        result.is_task = True
        result.evidence = matched
        result.requires_tool_likely = True

        # Classify intent type
        text_lower = text.lower()
        if any(w in text_lower for w in ("巡检", "inspection", "inspect")):
            result.intent_type = "inspection"
        elif any(w in text_lower for w in ("报文", "pcap", "抓包")):
            result.intent_type = "pcap_analysis"
        elif any(w in text_lower for w in ("文件", "file", "read", "读取", "日志", "log")):
            result.intent_type = "file_read_analysis"
        elif any(w in text_lower for w in ("配置", "config")):
            result.intent_type = "config_analysis"
        elif any(w in text_lower for w in ("命令", "执行", "exec", "show", "ping")):
            result.intent_type = "command_check"
        elif any(w in text_lower for w in ("诊断", "排查", "问题", "异常", "故障", "起不来")):
            result.intent_type = "analysis"
        elif any(w in text_lower for w in ("报告", "report", "导出")):
            result.intent_type = "report"
        elif any(w in text_lower for w in ("分析", "总结", "判断")):
            result.intent_type = "analysis"
        else:
            result.intent_type = "analysis"

        return result

    # Step 3: Check for "截图"/"为什么这样" patterns without explicit verbs
    if any(p in text for p in ("为什么", "这个截图", "为什么会", "看看有问题")):
        result.is_task = True
        result.evidence = ["contextual_inquiry"]
        result.intent_type = "analysis"
        result.requires_tool_likely = True

    return result


def task_intent_to_default_tool(intent_type: str) -> str | None:
    """Return the recommended default tool for a task intent type."""
    return _TASK_TO_DEFAULT_TOOL.get(intent_type)


# ── v3.15: Final-response validator ───────────────────────────────────────

_TASK_ANALYSIS_FIELDS = (
    "结论", "发现", "原因", "建议", "异常", "正常",
    "风险", "下一步", "依据", "诊断",
)

_TASK_BUSINESS_RESULT_FIELDS = (
    "状态", "数量", "失败设备", "跳过设备", "报告链接",
    "stdout", "接口", "会话", "重传", "丢包", "RST",
    "超时", "SYN", "ACK", "三次握手", "四次挥手",
    "IP", "TCP", "端口", "源地址", "目标地址",
    "成功数", "失败数", "巡检结果", "检查结果",
    "分析结论", "报文分析", "设备状态",
)

_TASK_BOGUS_RESPONSE_PATTERNS = (
    "工具执行成功", "结果已返回",
    "文件已读取，可以继续",
    "巡检任务已创建，请稍后",
    "已完成本次操作",
    "数据已获取，未发现更多",
    "收到",
    "已完成",
    "No tools were executed",
    "readartifact completed",
    "readartifact succeeded",
    "Completed",
)


class FinalResponseValidatorResult:
    valid: bool = True
    reason: str = ""
    matched_placeholder: str = ""
    should_retry_finalizer: bool = False
    has_analysis_fields: bool = False
    has_business_result: bool = False
    has_explicit_failure_reason: bool = False
    placeholder_like: bool = False


def validate_final_response(
    user_input: str,
    final_response: str,
) -> FinalResponseValidatorResult:
    """Validate that the final_response actually completes the user's task."""
    rr = FinalResponseValidatorResult()

    task = detect_task_intent(user_input)
    if not task.is_task:
        return rr

    response = (final_response or "").strip()
    if not response:
        rr.valid = False
        rr.reason = "empty response for task request"
        rr.should_retry_finalizer = True
        return rr

    # ── Step 1: check analysis / business-result fields ───────────
    rr.has_analysis_fields = any(f in response for f in _TASK_ANALYSIS_FIELDS)
    rr.has_business_result = any(f in response for f in _TASK_BUSINESS_RESULT_FIELDS)

    # Explicit failure reason ("缺少"/"无法"/"不足" + 分析意图)
    rr.has_explicit_failure_reason = (
        any(w in response for w in ("缺少", "无法完成", "不足", "没有可分析", "未返回"))
        and ("分析" in response or "内容" in response or "数据" in response or "报文" in response)
    )

    if rr.has_analysis_fields or rr.has_business_result or rr.has_explicit_failure_reason:
        return rr  # valid

    # ── Step 2: detect placeholder-like patterns ──────────────────
    rr.placeholder_like = any(p in response for p in _TASK_BOGUS_RESPONSE_PATTERNS)
    if rr.placeholder_like:
        rr.valid = False
        rr.reason = f"placeholder-like response"
        rr.matched_placeholder = "bogus_pattern"
        rr.should_retry_finalizer = True
        return rr

    # ── Step 3: very short response without analysis → invalid ────
    if len(response) < 30:
        rr.valid = False
        rr.reason = "very short response without analysis fields"
        rr.should_retry_finalizer = True
        return rr

    # ── Step 4: longer but still looks like no analysis completed ─
    # (e.g. "我已经读取了文件，工具执行成功，数据已返回...")
    _no_analysis_words = ("可以继续", "已获取", "已返回", "已读取", "请稍后")
    if any(w in response for w in _no_analysis_words):
        rr.valid = False
        rr.reason = "response mentions tool success but no analysis"
        rr.should_retry_finalizer = True
        return rr

    return rr


# ── v6: Convergence validation gates ───────────────────────────────────────


def _v6_validate_tool_truth(node_results: dict) -> None:
    """v6: every tool result has error_code_norm populated."""
    for nid, r in node_results.items():
        assert r.error_code_norm is not None, (
            f"node {nid}: error_code_norm is None"
        )


def _v6_validate_causal_order(ctx) -> None:
    """v6: ctx carries causal_order_valid flag."""
    assert ctx.extras.get("causal_order_valid"), (
        "causal_order_valid flag missing from context"
    )


def _v6_validate_plan_consistency(ctx) -> None:
    """v6: plan was schema-validated."""
    assert ctx.extras.get("plan_schema_validated"), (
        "plan_schema_validated flag missing from context"
    )


# Backward-compatible aliases
# ── Ultimate Stability: issue collector ────────────────────────────────────


def _collect_stability_issues(ctx, result, errors, collector) -> None:
    """v6+: collect all runtime issues into a stability report.

    Classifies errors, tool failures, contract violations, and
    missing context into a single IssueCollector so the terminal
    stop-condition gate can decide whether the system is stable.
    """
    from .runtime_stability import Severity, IssueCategory

    # Tool errors → TOOL category
    if result.node_results:
        for nid, tr in result.node_results.items():
            if not tr.success:
                collector.add(
                    Severity.HIGH, IssueCategory.TOOL,
                    f"tool:{tr.tool}", str(tr.error or ""),
                    node_id=nid,
                    error_code_norm=tr.error_code_norm,
                )

    # Structured errors from pipeline
    structured = result.metadata.get("structured_errors", [])
    for se in structured:
        sev = Severity.HIGH if se.get("risk_level") in ("high", "critical") else Severity.MEDIUM
        category = IssueCategory.CONTRACT if "CONTRACT" in str(se.get("code", "")) else IssueCategory.EXECUTION
        collector.add(
            sev, category,
            se.get("stage", "engine"),
            se.get("message", ""),
            code=se.get("code"),
        )

    # Context injection failures
    if ctx.extras.get("conversation_context_error"):
        collector.add(
            Severity.MEDIUM, IssueCategory.CONTEXT,
            "speg_adapter._inject_conversation_context",
            str(ctx.extras["conversation_context_error"]),
        )

    # Empty result but had task intent
    if not result.node_results and not result.final_response:
        collector.add(
            Severity.HIGH, IssueCategory.EXECUTION,
            "engine.run",
            "no tool results and no final response",
        )


def plan_nodes_empty_for_task(user_input: str) -> bool:
    return detect_task_intent(user_input).is_task


def _is_task_incomplete_final_response(user_input: str, final_response: str) -> bool:
    vr = validate_final_response(user_input, final_response)
    return not vr.valid
