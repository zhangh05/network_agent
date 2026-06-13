# agent/tools/schemas.py
"""ToolSpec and LLMToolSpec — tool metadata."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ToolSpec:
    tool_id: str = ""
    name: str = ""
    category: str = ""
    description: str = ""
    risk_level: str = "low"
    enabled: bool = True
    requires_approval: bool = False
    input_schema: dict = field(default_factory=dict)
    callable_by_llm: bool = True
    forbidden: bool = False
    source: str = "runtime"
    timeout_seconds: int = 30
    permission_action: str = ""  # read | write | exec | network


@dataclass
class LLMToolSpec:
    name: str = ""           # LLM-safe name (__ format)
    description: str = ""
    parameters: dict = field(default_factory=dict)
    real_tool_id: str = ""   # real tool_id (. format)

    def to_openai_function(self) -> dict:
        """Convert to OpenAI function calling format."""
        parameters = dict(self.parameters or {})
        parameters.setdefault("type", "object")
        parameters.setdefault("properties", {})
        parameters.setdefault("required", [])
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": parameters,
            },
        }
