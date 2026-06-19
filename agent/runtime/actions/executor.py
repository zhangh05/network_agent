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

    def execute(self, plan: ActionPlan, tool_call: Any, context: Any,
                metadata: dict = None) -> ActionResult:
        """Execute an action plan through the full pipeline.

        Returns an ActionResult with all fields populated.
        """
        if metadata is None:
            metadata = {}

        # 1. Risk evaluation
        risk = self.risk_policy.evaluate(plan)

        # Update plan from risk decision
        plan.risk_level = risk.risk_level
        plan.approval_required = risk.approval_required

        # 2. Audit the plan
        self.audit.record_plan(plan, risk, metadata)

        # 3. Approval gate
        approval = self.approval_gate.decide(plan, risk)

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
            self.audit.record_result(result, metadata)
            return result

        # If approval pending → return without dispatching
        if approval.status == "pending":
            result = ActionResult(
                action_id=plan.action_id,
                tool_call_id=plan.tool_call_id,
                tool_name=plan.tool_name,
                tool_id=plan.tool_id,
                ok=False,
                status="pending_approval",
                error="Action requires approval",
                error_type="approval_pending",
                metadata={"approval": {
                    "status": approval.status,
                    "reason": approval.reason,
                    "prompt": approval.prompt,
                }},
            )
            self.audit.record_result(result, metadata)
            return result

        # 4. Dispatch
        result = self.dispatcher.dispatch(plan, tool_call, context)

        # 5. Normalize
        self.normalizer.normalize(result)

        # 6. Scan
        self.scanner.scan(result)

        # 7. Retry check (for informational purposes; actual retry is caller's job)
        if not result.ok:
            result.retryable = self.retry_policy.should_retry(plan, result, risk)

        # 8. Audit result
        self.audit.record_result(result, metadata)

        # 9. Evidence update
        if result.ok:
            self.evidence.update(plan, result)

        return result
