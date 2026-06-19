# agent/runtime/actions/audit.py
"""ActionAuditTrail — records action plan and result to metadata."""

from __future__ import annotations

from typing import Any

from agent.runtime.actions.models import ActionPlan, ActionResult, RiskDecision


class ActionAuditTrail:
    """Record action execution trace into context metadata."""

    def record_plan(self, plan: ActionPlan, risk: RiskDecision,
                    metadata: dict, *, ctx=None) -> None:
        """Record an action plan to the trace."""
        entry = {
            "type": "plan",
            "action_id": plan.action_id,
            "tool_id": plan.tool_id,
            "action_class": plan.action_class,
            "risk_level": risk.risk_level,
            "approval_required": risk.approval_required,
            "blocked": risk.blocked,
        }
        trace = metadata.setdefault("action_trace", [])
        trace.append(entry)
        # Also write to ctx.metadata when provided
        if ctx is not None:
            ctx_meta = getattr(ctx, "metadata", None)
            if ctx_meta is not None and ctx_meta is not metadata:
                ctx_trace = ctx_meta.setdefault("action_trace", [])
                ctx_trace.append(entry)

    def record_result(self, result: ActionResult, metadata: dict,
                      *, ctx=None) -> None:
        """Record an action result to the trace."""
        entry = {
            "type": "result",
            "action_id": result.action_id,
            "tool_id": result.tool_id,
            "ok": result.ok,
            "status": result.status,
            "latency_ms": result.latency_ms,
            "scan_status": result.scan_status,
            "error": result.error[:200] if result.error else "",
        }
        trace = metadata.setdefault("action_trace", [])
        trace.append(entry)
        # Also write to ctx.metadata when provided
        if ctx is not None:
            ctx_meta = getattr(ctx, "metadata", None)
            if ctx_meta is not None and ctx_meta is not metadata:
                ctx_trace = ctx_meta.setdefault("action_trace", [])
                ctx_trace.append(entry)
