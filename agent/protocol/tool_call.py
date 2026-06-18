# agent/protocol/tool_call.py
"""ToolCall — LLM-requested tool invocation."""

from dataclasses import dataclass, field


@dataclass
class ToolCall:
    call_id: str = ""
    llm_tool_name: str = ""       # LLM-safe name (with __)
    real_tool_id: str = ""        # Real tool_id (with .)
    arguments: dict = field(default_factory=dict)
    source: str = "llm"           # llm | system | deterministic
