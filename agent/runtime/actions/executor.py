# agent/runtime/actions/executor.py
"""ActionExecutor — orchestrates the action execution pipeline.

Pipeline: RiskPolicy → ApprovalGate → ToolDispatcher → ResultNormalizer
          → ResultScanner → RetryPolicy → AuditTrail → EvidenceUpdate
"""

from __future__ import annotations

import time
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
        risk = self.risk_policy.evaluate(plan, ctx=ctx)

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

        # If approval pending → return without dispatching
        if approval.status == "pending":
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
    """Emit tool-level events for pipeline compatibility."""
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
