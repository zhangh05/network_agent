# agent/runtime/tool_execution/result_stage.py
"""ResultStage — append tool result to messages and result list."""

import json

from agent.runtime.tool_result_utils import to_standard_tool_call, build_tool_message_payload
from agent.protocol.message import ToolResultMessage


class ResultStage:
    """Format and append a tool result to messages and all_tool_results."""

    def run(self, result, tool_call, tc, all_tool_results, messages):
        append_tool_result(result, tool_call, tc, all_tool_results, messages)


def append_tool_result(result, tool_call, tc, all_tool_results, messages):
    """Append a tool result to the result list and message list."""
    all_tool_results.append(to_standard_tool_call(tool_call.call_id, tool_call.real_tool_id, result))
    tool_msg_payload = build_tool_message_payload(result)

    # Injection scan
    try:
        from agent.runtime.rag_injection_scan import scan_tool_result_payload
        is_knowledge = tool_call.real_tool_id.startswith("knowledge.")
        src_type = "knowledge" if is_knowledge else ""
        tool_msg_payload = scan_tool_result_payload(
            tool_msg_payload,
            tool_id=tool_call.real_tool_id,
            source="tool_output",
            source_type=src_type,
        )
    except Exception:
        pass

    serialized_payload = json.dumps(tool_msg_payload, ensure_ascii=False)
    tool_msg = ToolResultMessage(
        content=serialized_payload,
        tool_call_id=tc.id if hasattr(tc, 'id') else tc.get("id", ""),
    )
    messages.append(tool_msg.to_llm_message())


