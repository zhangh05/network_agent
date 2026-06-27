# agent/runtime/actions/executor.py
"""ActionExecutor — orchestrates the action execution pipeline.

Pipeline: RiskPolicy → ApprovalGate → ToolDispatcher → ResultNormalizer
          → ResultScanner → RetryPolicy → AuditTrail → EvidenceUpdate
"""

from __future__ import annotations

from typing import Any

from agent.runtime.actions.models import ActionPlan, ActionResult
from agent.runtime.actions.risk import RiskPolicy
from agent.runtime.actions.approval import ApprovalGate
from agent.runtime.actions.dispatcher import ToolDispatcher
from agent.runtime.actions.result import ResultNormalizer
from agent.runtime.actions.scanner import ResultScanner
from agent.runtime.actions.retry import RetryPolicy
from agent.runtime.actions.audit import ActionAuditTrail
from agent.runtime.actions.evidence_update import EvidenceUpdate


class ActionExecutor:
    """Orchestrate the full action execution pipeline."""

    def __init__(self):
        self.risk_policy = RiskPolicy()
        self.approval_gate = ApprovalGate()
        self.dispatcher = ToolDispatcher()
        self.normalizer = ResultNormalizer()
        self.scanner = ResultScanner()
        self.retry_policy = RetryPolicy()
        self.audit = ActionAuditTrail()
        self.evidence = EvidenceUpdate()

    def execute(self, plan: ActionPlan, *, tool_call: Any, ctx: Any,
                state: Any = None, events: Any = None,
                step: int = 0) -> ActionResult:
        """Execute an action plan through the full pipeline.

        Returns an ActionResult with all fields populated.
        """
        # Derive a metadata dict for audit recording
        ctx_meta = getattr(ctx, "metadata", None) if ctx is not None else None
        metadata = ctx_meta if ctx_meta is not None else {}

        # 1. Risk evaluation
        evidence_bundle = getattr(ctx, "evidence_bundle", None) if ctx is not None else None
        risk = self.risk_policy.evaluate(plan, ctx=ctx, evidence_bundle=evidence_bundle)

        # Update plan from risk decision
        plan.risk_level = risk.risk_level
        plan.approval_required = risk.approval_required

        # 2. Audit the plan
        self.audit.record_plan(plan, risk, metadata, ctx=ctx)

        # 3. Approval gate
        approval = self.approval_gate.decide(plan, risk, ctx=ctx)

        # If blocked → return immediately
        if risk.blocked:
            result = ActionResult(
                action_id=plan.action_id,
                tool_call_id=plan.tool_call_id,
                tool_name=plan.tool_name,
                tool_id=plan.tool_id,
                ok=False,
                status="blocked",
                error=risk.reason,
                error_type="risk_blocked",
            )
            if events is not None:
                _emit_events(events, plan.tool_id, step, result)
            self.audit.record_result(result, metadata, ctx=ctx)
            return result

        # If approval pending → interrupt (Phase 4: never block, always checkpoint)
        if approval.status == "pending":
            # v3.10 Phase 4: interrupt_before_tool
            try:
                from agent.runtime.durable.models import RuntimeStep as DStep
                from agent.runtime.durable.interrupt import interrupt_before_tool
                ws = ""
                sid = ""
                rid = ""
                if state is not None:
                    ws = getattr(getattr(state, 'session', None), 'workspace_id', '') or \
                         getattr(getattr(state, 'context', None), 'workspace_id', '') or ''
                    sid = getattr(getattr(state, 'session', None), 'session_id', '') or ''
                    rid = getattr(getattr(state, 'turn', None), 'turn_id', '') or ''
                # v3.10: Use state.task_id (bound by runner), fallback to store query
                real_task_id = getattr(state, 'task_id', '') or ''
                if not (ws and sid and real_task_id):
                    raise RuntimeError("approval interrupt requires workspace_id, session_id, and task_id")
                step_id_str = f"step-{plan.tool_id}-{step}"
                interrupt_before_tool(
                    task_id=real_task_id,
                    ws_id=ws, session_id=sid, run_id=rid,
                    step_id=step_id_str,
                    tool_invocation={
                        "tool_id": plan.tool_id,
                        "arguments": dict(plan.arguments) if hasattr(plan, 'arguments') else {},
                    },
                    risk_decision={
                        "risk_level": risk.risk_level,
                        "reason": risk.reason or "High-risk action requires approval",
                    },
                )
            except Exception as _irq_exc:
                msg = str(_irq_exc)[:200]
                result = ActionResult(
                    action_id=plan.action_id,
                    tool_call_id=plan.tool_call_id,
                    tool_name=plan.tool_name,
                    tool_id=plan.tool_id,
                    ok=False,
                    status="error",
                    error=f"interrupt setup failed: {msg}",
                    error_type="interrupt_error",
                )
                if events is not None:
                    _emit_events(events, plan.tool_id, step, result)
                self.audit.record_result(result, metadata, ctx=ctx)
                return result

            result = ActionResult(
                action_id=plan.action_id,
                tool_call_id=plan.tool_call_id,
                tool_name=plan.tool_name,
                tool_id=plan.tool_id,
                ok=False,
                status="approval_pending",
                error="Action requires approval",
                error_type="approval_pending",
                metadata={"approval": {
                    "status": approval.status,
                    "reason": approval.reason,
                    "prompt": approval.prompt,
                }},
            )
            if events is not None:
                _emit_events(events, plan.tool_id, step, result)
            self.audit.record_result(result, metadata, ctx=ctx)
            return result

        # 4. Dispatch
        result = self.dispatcher.dispatch(plan, tool_call, ctx=ctx, state=state)

        # 5. Normalize
        self.normalizer.normalize(result)

        # 6. Scan
        self.scanner.scan(result)

        # 7. Retry check (informational; actual retry is caller's job)
        if not result.ok:
            result.retryable = self.retry_policy.should_retry(plan, result, risk)

        # 8. Record events
        if events is not None:
            _emit_events(events, plan.tool_id, step, result)

        # 9. Audit result
        self.audit.record_result(result, metadata, ctx=ctx)

        # 10. Evidence update
        if result.ok:
            self.evidence.update(plan, result, ctx=ctx)

        return result


def _emit_events(events, tid: str, step: int, result: ActionResult) -> None:
    """Emit tool-level events for the execution pipeline."""
    ok = result.ok
    summary = ""
    if result.error:
        summary = result.error[:200]
    elif hasattr(result.result, "summary"):
        summary = getattr(result.result, "summary", "")[:200]
    else:
        summary = result.status

    if ok:
        if hasattr(events, "tool_call_completed"):
            events.tool_call_completed(tid, ok, summary)
    else:
        if hasattr(events, "tool_call_failed"):
            errors = [result.error[:200]] if result.error else [result.status]
            events.tool_call_failed(tid, errors)

    if hasattr(events, "record_tool_result"):
        events.record_tool_result(step, tid, ok, summary)
