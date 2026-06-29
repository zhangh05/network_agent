# agent/runtime/actions/dispatcher.py
"""ToolDispatcher — wraps existing tool dispatch via tool_router.

Uses the same dispatch mechanism as DispatchStage: ctx.tool_router.dispatch().
"""

from __future__ import annotations

from typing import Any

from agent.protocol.tool_result import ToolResult
from agent.runtime.actions.models import ActionPlan, ActionResult
from agent.runtime.utils import duration_ms, now_iso


class ToolDispatcher:
    """Dispatch a planned action through the existing tool_router."""

    def dispatch(self, plan: ActionPlan, tool_call: Any, *,
                 ctx: Any, state: Any = None) -> ActionResult:
        """Execute the tool call via ctx.tool_router.dispatch().

        Uses the same mechanism as dispatch_stage.py.  When *state* is
        provided, ``state.context`` is used as a fallback context.

        Returns an ActionResult with raw result or error.

        v3.9.8: started_at / finished_at are ISO-8601 strings (matching
        RuntimeStep / TrajectoryRecord); latency_ms is int (matching
        ToolResult.duration_ms). Was float-epoch before.
        """
        result = ActionResult(
            action_id=plan.action_id,
            tool_call_id=plan.tool_call_id,
            tool_name=plan.tool_name,
            tool_id=plan.tool_id,
            status="failed",
            started_at=now_iso(),
            attempts=1,
        )

        # Resolve context: prefer explicit ctx, fall back to state.context
        dispatch_ctx = ctx
        if dispatch_ctx is None and state is not None:
            dispatch_ctx = getattr(state, "context", None)

        try:
            raw = dispatch_ctx.tool_router.dispatch(tool_call, dispatch_ctx)
            result.result = raw
            result.ok = getattr(raw, "ok", False) if raw is not None else False
            result.status = "success" if result.ok else "failed"
        except Exception as e:
            result.ok = False
            result.status = "failed"
            result.error = str(e)[:500]
            result.error_type = type(e).__name__

        result.finished_at = now_iso()
        result.latency_ms = duration_ms(result.started_at, result.finished_at)
        return result
