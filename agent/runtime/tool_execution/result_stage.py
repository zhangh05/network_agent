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

    _has_large = any(k in tool_msg_payload for k in (
        "content", "preview", "diff", "rendered", "document",
        "table", "markdown", "mermaid", "translated_config",
        "stdout", "stderr", "output", "text", "results", "items",
        "chunks", "hits", "result_stdout", "result_stderr",
        "result_output", "result_text",
    )) or len(json.dumps(tool_msg_payload, ensure_ascii=False)) > 8000
    trunc_limit = 20000 if _has_large else 8000
    serialized_payload = json.dumps(tool_msg_payload, ensure_ascii=False)
    tool_msg = ToolResultMessage(
        content=preserve_tool_payload_edges(serialized_payload, trunc_limit),
        tool_call_id=tc.id if hasattr(tc, 'id') else tc.get("id", ""),
    )
    messages.append(tool_msg.to_llm_message())


def preserve_tool_payload_edges(text: str, limit: int) -> str:
    """Truncate text while retaining useful content from both edges."""
    if len(text) <= limit:
        return text
    from agent.protocol.tool_result import _safe_truncate_utf8
    marker = f'\n"...[truncated middle, {len(text)} chars total]..."\n'
    keep = max(0, limit - len(marker))
    head = max(keep * 2 // 3, keep // 2)
    tail = keep - head
    head_str = _safe_truncate_utf8(text[:head] if head > 0 else "", head)
    tail_str = _safe_truncate_utf8(text[-tail:] if tail > 0 else "", tail)
    return head_str + marker + tail_str
