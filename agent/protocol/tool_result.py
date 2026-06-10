# agent/protocol/tool_result.py
"""ToolResult — tool execution result."""

from dataclasses import dataclass, field


@dataclass
class ToolResult:
    call_id: str = ""
    tool_id: str = ""
    ok: bool = False
    summary: str = ""
    content: str = ""
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    raw: dict = field(default_factory=dict)
