# agent/runtime/tool_execution/dispatch_stage.py
"""DispatchStage — dispatch tool call via the tool router."""

from agent.protocol.tool_result import ToolResult


class DispatchStage:
    """Dispatch the tool call and return the ToolResult."""

    def run(self, state, tool_call, events, step):
        tid = tool_call.real_tool_id
        try:
            result = state.context.tool_router.dispatch(tool_call, state.context)
        except Exception as e:
            result = ToolResult(ok=False, summary=str(e)[:200], errors=[str(e)[:200]])

        # Audit
        ok = result.ok if hasattr(result, 'ok') else False
        summary = (result.summary if hasattr(result, 'summary') else str(result))[:200]
        events.tool_call_completed(tid, ok, summary)
        events.record_tool_result(step, tid, ok, summary)

        return result
