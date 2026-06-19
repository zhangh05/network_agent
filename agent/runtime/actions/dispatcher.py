# agent/runtime/actions/dispatcher.py
"""ToolDispatcher — wraps existing tool dispatch via tool_router."""

from __future__ import annotations

import time
from typing import Any

from agent.runtime.actions.models import ActionPlan, ActionResult


class ToolDispatcher:
    """Dispatch a planned action through the existing tool_router."""

    def dispatch(self, plan: ActionPlan, tool_call: Any, context: Any) -> ActionResult:
        """Execute the tool call via context.tool_router.dispatch().

        Returns an ActionResult with raw result or error.
        """
        result = ActionResult(
            action_id=plan.action_id,
            tool_call_id=plan.tool_call_id,
            tool_name=plan.tool_name,
            tool_id=plan.tool_id,
            status="executing",
            started_at=time.time(),
            attempts=1,
        )

        try:
            raw = context.tool_router.dispatch(tool_call, context)
            result.result = raw
            result.ok = getattr(raw, "ok", False) if raw is not None else False
            result.status = "completed"
        except Exception as e:
            result.ok = False
            result.status = "failed"
            result.error = str(e)[:500]
            result.error_type = type(e).__name__

        result.finished_at = time.time()
        result.latency_ms = (result.finished_at - result.started_at) * 1000
        return result
