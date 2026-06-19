# agent/runtime/actions/dispatcher.py
"""ToolDispatcher — wraps existing tool dispatch via tool_router.

Uses the same dispatch mechanism as DispatchStage: ctx.tool_router.dispatch().
"""

from __future__ import annotations

import time
from typing import Any

from agent.protocol.tool_result import ToolResult
from agent.runtime.actions.models import ActionPlan, ActionResult


class ToolDispatcher:
    """Dispatch a planned action through the existing tool_router."""

    def dispatch(self, plan: ActionPlan, tool_call: Any, *,
                 ctx: Any, state: Any = None) -> ActionResult:
        """Execute the tool call via ctx.tool_router.dispatch().

        Uses the same mechanism as dispatch_stage.py.  When *state* is
        provided, ``state.context`` is used as a fallback context.

        Returns an ActionResult with raw result or error.
        """
        result = ActionResult(
            action_id=plan.action_id,
            tool_call_id=plan.tool_call_id,
            tool_name=plan.tool_name,
            tool_id=plan.tool_id,
            status="failed",
            started_at=time.time(),
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

        result.finished_at = time.time()
        result.latency_ms = (result.finished_at - result.started_at) * 1000
        return result
