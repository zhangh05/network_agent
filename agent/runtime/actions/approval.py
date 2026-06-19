# agent/runtime/actions/approval.py
"""ApprovalGate — decides approval status based on risk decision."""

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
            decision.reason = risk.reason or "High-risk action requires approval"
            decision.prompt = f"Approve {plan.tool_id}({_summarize_args(plan.arguments)})?"
            self._write_ctx(ctx, decision)
            return decision

        # Low/medium → no approval needed
        decision.required = False
        decision.approved = True
        decision.status = "not_required"
        decision.reason = "Low-risk action, no approval needed"
        self._write_ctx(ctx, decision)
        return decision

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
