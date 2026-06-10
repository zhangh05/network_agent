# agent/tools/registry.py
"""ToolRegistry — wraps ToolRuntimeClient, filters disabled/forbidden."""

from agent.tools.schemas import ToolSpec
from agent.llm.tool_adapter import to_llm_tool_name


class ToolRegistry:
    def __init__(self):
        self._specs: dict = {}       # tool_id → ToolSpec
        self._tool_client = None

    @classmethod
    def from_runtime_client(cls, client) -> "ToolRegistry":
        """Build registry from existing ToolRuntimeClient."""
        reg = cls()
        reg._tool_client = client
        try:
            raw_tools = client.list_tools()
            for t in raw_tools:
                spec = ToolSpec(
                    tool_id=t.get("tool_id", ""),
                    name=t.get("tool_id", ""),
                    category=t.get("category", ""),
                    description=t.get("description", ""),
                    risk_level=t.get("risk_level", "low"),
                    enabled=t.get("enabled", True),
                    requires_approval=t.get("requires_approval", False),
                    input_schema=t.get("input_schema", {}),
                    callable_by_llm=t.get("callable_by_llm", True),
                    forbidden=t.get("forbidden", False),
                    source=t.get("source", "runtime"),
                )
                reg._specs[spec.tool_id] = spec
        except Exception:
            pass
        return reg

    def list_all(self) -> list:
        return list(self._specs.values())

    def list_model_visible(self) -> list:
        """Tools visible to LLM: enabled + not forbidden + callable_by_llm."""
        return [s for s in self._specs.values()
                if s.enabled and not s.forbidden and s.callable_by_llm]

    def get(self, tool_id: str) -> ToolSpec:
        return self._specs.get(tool_id)

    def dispatch(self, tool_id: str, args: dict, context=None) -> dict:
        """Execute tool via ToolRuntimeClient."""
        if self._tool_client is None:
            return {"ok": False, "status": "failed", "summary": "No tool client", "errors": ["no tool client"]}
        try:
            from agent.tool_runtime.invoke import invoke_tool
            result = invoke_tool(tool_id, args, context)
            return result
        except Exception as e:
            return {"ok": False, "status": "failed", "summary": str(e)[:200], "errors": [str(e)[:200]]}
