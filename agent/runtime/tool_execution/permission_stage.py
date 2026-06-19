# agent/runtime/tool_execution/permission_stage.py
"""PermissionStage — check tool permission via the permission matrix."""

from agent.runtime.permission_check import (
    check_tool_permission, build_permission_denied_result,
)
from agent.protocol.tool_result import ToolResult


class PermissionStage:
    """Check if a tool call is permitted by the permission matrix."""

    def run(self, state, tool_call, events, step):
        """Returns (denied_result_or_None, denied_bool, requires_approval, spec, risk_level)."""
        tid = tool_call.real_tool_id
        spec = (state.context.tool_router.registry.get(tid)
                if hasattr(state.context.tool_router, 'registry') else None)
        risk_level = getattr(spec, 'risk_level', 'low') if spec else 'low'

        requires_approval, denied, decision = check_tool_permission(
            tid, spec, state.context, state.turn)

        if denied:
            result = build_permission_denied_result(tid)
            events.tool_call_failed(tid, result.errors)
            events.record_tool_result(step, tid, False, result.summary)
            return result, True, False, spec, risk_level  # denied

        return None, False, requires_approval, spec, risk_level
