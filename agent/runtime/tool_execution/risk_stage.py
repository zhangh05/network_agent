# agent/runtime/tool_execution/risk_stage.py
"""RiskStage — analyze tool arguments for risk before approval/dispatch."""

from agent.runtime.tool_argument_risk import analyze_tool_arguments, _detect_argument_source
from agent.protocol.tool_result import ToolResult


class RiskStage:
    """Analyze tool argument risk. Returns a blocked ToolResult if risk is too high."""

    def run(self, state, tool_call, spec, risk_level, events, step):
        tid = tool_call.real_tool_id
        arg_source = _detect_argument_source(
            tool_call.arguments,
            getattr(state.context, 'user_input', ""),
            getattr(state.context, 'safe_context', None),
        )
        arg_risk = analyze_tool_arguments(
            tool_id=tid,
            arguments=tool_call.arguments,
            argument_source=arg_source,
            user_input=getattr(state.context, 'user_input', ""),
            risk_level=risk_level,
        )
        if arg_risk.blocked:
            events.tool_call_failed(tid, [arg_risk.reason])
            events.record_tool_result(step, tid, False, "argument_risk_blocked")
            result = ToolResult(ok=False, summary=arg_risk.reason, errors=[arg_risk.reason])
            return result, True, arg_source, arg_risk

        return None, False, arg_source, arg_risk
