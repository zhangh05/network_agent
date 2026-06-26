# agent/runtime/tool_execution/approval_stage.py
"""ApprovalStage — gate tool execution on user approval when required."""

from agent.runtime.permission_check import needs_approval, check_shell_safety, build_shell_denied_result
from agent.runtime.hook_runner import run_approval_hook
from agent.protocol.tool_result import ToolResult


class ApprovalStage:
    """Handle approval flow for high-risk tool calls."""

    def run(self, state, tool_call, spec, risk_level, requires_approval,
            arg_source, arg_risk, events, step):
        tid = tool_call.real_tool_id

        if not needs_approval(tid, spec, risk_level, requires_approval):
            return None, False  # no approval needed

        # Shell safety check
        safe, denied_word = check_shell_safety(tid, tool_call.arguments)
        if not safe:
            result = build_shell_denied_result(tid, denied_word)
            events.tool_call_failed(tid, ["unsafe_command_denied"])
            events.record_tool_result(step, tid, False, "unsafe_command_denied")
            return result, True  # denied

        # Create approval request
        from agent.approval import get_approval_store
        store = get_approval_store()
        apr = store.create(
            session_id=state.session.session_id,
            tool_id=tid,
            arguments=tool_call.arguments,
            description=getattr(spec, 'description', '')[:200],
            risk_level=risk_level,
            workspace_id=getattr(state, 'workspace_id', '') or getattr(state.session, 'workspace_id', ''),
            run_id=getattr(state, 'run_id', ''),
            job_id=getattr(state, 'job_id', ''),
            metadata={
                "argument_source": arg_source,
                "argument_risk": arg_risk.risk_level,
                "recommendation": arg_risk.recommendation or "",
                "reason": arg_risk.reason or "",
            },
        )

        events.approval_required(apr.approval_id, apr.tool_id)
        run_approval_hook(state.session, "required", apr.approval_id, apr.tool_id, state.context)

        # Wait for approval
        from agent.runtime.loop import _get_approval_timeout
        is_sub_agent = bool(getattr(state.session, 'is_sub_agent', False))
        timeout = _get_approval_timeout(is_sub_agent=is_sub_agent)
        allowed = store.wait(apr.approval_id, timeout=timeout)
        store.cleanup(apr.approval_id)

        if not allowed:
            run_approval_hook(state.session, "denied", apr.approval_id, apr.tool_id, state.context)
            result = ToolResult(
                ok=False,
                summary=f"Tool {tid} was rejected by user",
                errors=["user_rejected"],
            )
            events.approval_denied(apr.tool_id)
            events.record_tool_result(step, tid, False, "user_rejected")
            return result, True  # denied
        else:
            run_approval_hook(state.session, "allowed", apr.approval_id, apr.tool_id, state.context)

        return None, False  # approved
