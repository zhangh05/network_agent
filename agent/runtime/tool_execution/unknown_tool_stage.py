# agent/runtime/tool_execution/unknown_tool_stage.py
"""Handle unknown or un-parseable tool calls from the LLM."""

import json

from agent.protocol.message import ToolResultMessage


def handle_unknown_tool(tc, llm_name, error, all_tool_results, messages,
                        audit_events, audit_trace, session, turn, step):
    """Handle an unknown / un-parseable tool call from the LLM."""
    error_name = getattr(error, '__class__', type(error)).__name__
    if audit_events:
        audit_events.emit("tool_call_failed", session_id=session.session_id, turn_id=turn.turn_id,
                          tool_id=llm_name, errors=[str(error)[:200]])
    if audit_trace:
        audit_trace.record_tool_result(turn.turn_id, step, llm_name, False, str(error)[:100])

    from agent.tools.router import ToolArgumentParseError
    is_arg_parse_error = isinstance(error, ToolArgumentParseError)

    summary = (
        f"Tool arguments not parseable: {str(error)[:160]}"
        if is_arg_parse_error
        else f"Tool not visible to model: {llm_name}"
    )
    all_tool_results.append({
        "tool_id": llm_name,
        "ok": False,
        "summary": summary[:200],
    })

    if is_arg_parse_error:
        hint = (
            "The arguments you sent for this tool are not a valid JSON object. "
            "Re-issue the tool call with `arguments` as a JSON object "
            "(e.g. {\"path\": \"/tmp/x\"}). Do not wrap the entire payload "
            "in quotes or include trailing prose."
        )
    else:
        hint = (
            "This tool is not available in your current function list. "
            "Use ONLY the tools provided. If you need to read a file, use workspace__file__read. "
            "If you need to parse a config, use network__config__parse. "
            "If a provided host exec tool is the best fit for local computation or diagnostics, "
            "call it and let the approval popup handle risk."
        )
    tool_msg = ToolResultMessage(
        content=json.dumps({
            "ok": False,
            "error": f"{error_name}: {str(error)[:200]}",
            "hint": hint,
        }, ensure_ascii=False)[:1200],
        tool_call_id=tc.id if hasattr(tc, 'id') else tc.get("id", ""),
    )
    messages.append(tool_msg.to_llm_message())
