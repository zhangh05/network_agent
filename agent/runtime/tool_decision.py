"""Tool decision transparency — build tool_decision and no_tool_reason blocks.

Extracted from loop.py to separate decision transparency from the agentic loop.
"""


def build_tool_decision(all_tool_results: list, context) -> dict:
    """Build the tool_decision block for AgentResult transparency.

    Shows what tools were considered, selected, and why.
    """
    if all_tool_results:
        selected_tools = [tc.get("tool_id", "") for tc in all_tool_results if tc.get("ok")]
        failed_tools = [tc.get("tool_id", "") for tc in all_tool_results if not tc.get("ok")]
        blocked = [tc for tc in all_tool_results if "rejected" in str(tc.get("errors", "")) or
                   "approval" in str(tc.get("errors", ""))]

        blocked_by = []
        if blocked:
            blocked_by = ["approval_required" if "approval" in str(b.get("errors", "")) or
                         "rejected" in str(b.get("errors", "")) else "unknown" for b in blocked]

        return {
            "needed": True,
            "selected_tools": selected_tools,
            "failed_tools": failed_tools,
            "blocked_by": blocked_by if blocked_by else [],
            "approval_required": any(
                tc.get("tool_id") in ("exec.run", "exec.python")
                for tc in all_tool_results
            ),
            "reason": "Tools were called to fulfill the user request.",
        }

    return {
        "needed": False,
        "reason": "Question could be answered from provided context without tool calls.",
    }


def build_no_tool_reason(all_tool_results: list, context) -> str:
    """Build a human-readable explanation for why no tools were called.

    Returns empty string if tools were called.
    """
    if all_tool_results:
        return ""

    visible_tools = getattr(context, 'visible_tool_ids', []) or []
    if not visible_tools:
        return "no_model_visible_tools: 当前 turn 没有可用工具"

    user_input = getattr(context, 'user_input', '') or ''
    tool_keywords = ("本机", "IP", "端口", "配置", "查询", "搜索", "翻译",
                     "读取", "保存", "生成", "解析", "验证", "记住", "知识")
    if any(kw in user_input for kw in tool_keywords):
        return "tools_not_called: 用户问题可能需要工具调用，但 LLM 未选择任何工具"

    return "tools_not_needed: 当前问题可直接回答，无需工具调用"


def build_partial_answer(tool_results: list) -> str:
    """Build partial answer when max steps exceeded."""
    if not tool_results:
        return "I've completed the analysis but need more information to provide a complete answer."
    parts = ["Here's what I've found so far:"]
    for tr in tool_results[-5:]:
        parts.append(f"- {tr.get('tool_id', 'unknown')}: {tr.get('summary', 'no result')}")
    return "\n".join(parts)


def collect_events(audit_events, turn_id: str) -> list:
    """Collect events for a turn from the event recorder."""
    if audit_events and hasattr(audit_events, 'events_for_turn_dicts'):
        return audit_events.events_for_turn_dicts(turn_id)
    return []
