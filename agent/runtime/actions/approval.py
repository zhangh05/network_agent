# agent/runtime/actions/approval.py
"""ApprovalGate — decides approval status based on risk decision.

When status is "pending", also creates an ApprovalStore record so the
frontend ApprovalBubble can discover it via /api/agent/approvals/pending.
"""

from __future__ import annotations

from agent.runtime.actions.models import ActionPlan, RiskDecision, ApprovalDecision


class ApprovalGate:
    """Decide approval status based on RiskDecision."""

    def decide(self, plan: ActionPlan, risk: RiskDecision,
               *, ctx=None) -> ApprovalDecision:
        """Return an ApprovalDecision based on risk evaluation."""
        decision = ApprovalDecision(action_id=plan.action_id)

        # Blocked → rejected immediately
        if risk.blocked:
            decision.required = True
            decision.approved = False
            decision.status = "rejected"
            decision.reason = risk.reason or "Action blocked by risk policy"
            self._write_ctx(ctx, decision)
            return decision

        # High or critical risk → pending approval
        if risk.risk_level in ("high", "critical", "medium-high"):
            decision.required = True
            decision.approved = False
            decision.status = "pending"
            # v3.10 Phase 5: read reason from Capability Manifest
            manifest_reason = risk.reason or ""
            try:
                from tool_runtime.manifest_registry import get_manifest
                m = get_manifest(plan.tool_id)
                if m and m.approval_reason_template:
                    manifest_reason = m.approval_reason_template
            except Exception:
                pass
            decision.reason = manifest_reason or risk.reason or "High-risk action requires approval"
            decision.prompt = f"Approve {plan.tool_id}({_summarize_args(plan.arguments)})?"
            self._write_ctx(ctx, decision)
            # v3.10: ApprovalStore record is now created by interrupt_before_tool() in durable/interrupt.py.
            # No duplicate store.create() here.
            return decision

        # Low/medium → no approval needed
        decision.required = False
        decision.approved = True
        decision.status = "not_required"
        decision.reason = "Low-risk action, no approval needed"
        self._write_ctx(ctx, decision)
        return decision

    @staticmethod
    def _create_store_record(plan: ActionPlan, risk: RiskDecision,
                              ctx, decision: ApprovalDecision) -> None:
        """Create an ApprovalStore record so the frontend can show the popup."""
        try:
            from agent.approval import get_approval_store
            store = get_approval_store()
            session_id = getattr(ctx, 'session_id', '') if ctx else ''
            workspace_id = getattr(ctx, 'workspace_id', '') if ctx else ''
            run_id = getattr(ctx, 'run_id', '') if ctx else ''
            job_id = getattr(ctx, 'job_id', '') if ctx else ''
            store.create(
                session_id=session_id,
                tool_id=plan.tool_id,
                arguments=dict(plan.arguments) if hasattr(plan, 'arguments') else {},
                description=getattr(plan, 'description', '') or f"{plan.tool_id}",
                risk_level=risk.risk_level,
                workspace_id=workspace_id,
                run_id=run_id,
                job_id=job_id,
                metadata={
                    "action_id": plan.action_id,
                    "reason": decision.reason,
                },
            )
        except Exception:
            pass  # ApprovalStore is best-effort; don't block execution

    @staticmethod
    def _write_ctx(ctx, decision: ApprovalDecision) -> None:
        """Write approval decision to ctx.metadata when ctx is provided."""
        if ctx is None:
            return
        meta = getattr(ctx, "metadata", None)
        if meta is None:
            return
        decisions = meta.setdefault("approval_decisions", [])
        decisions.append({
            "action_id": decision.action_id,
            "status": decision.status,
            "reason": decision.reason,
            "required": decision.required,
        })
        if decision.status == "pending":
            pending = meta.setdefault("pending_approvals", [])
            pending.append({
                "action_id": decision.action_id,
                "prompt": decision.prompt,
                "reason": decision.reason,
            })


def _summarize_args(arguments: dict, max_len: int = 80) -> str:
    """Create a short summary of arguments for approval prompt."""
    parts = []
    for k, v in arguments.items():
        sv = str(v)
        if len(sv) > 30:
            sv = sv[:27] + "..."
        parts.append(f"{k}={sv}")
    s = ", ".join(parts)
    if len(s) > max_len:
        s = s[:max_len - 3] + "..."
    return s
