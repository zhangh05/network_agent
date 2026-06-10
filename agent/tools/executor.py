# agent/tools/executor.py
"""ToolExecutor — wraps tool invoke (stub, delegates to registry)."""

from agent.tools.registry import ToolRegistry


class ToolExecutor:
    def __init__(self, registry: ToolRegistry = None):
        self.registry = registry or ToolRegistry()

    def invoke(self, tool_id: str, args: dict, context=None) -> dict:
        return self.registry.dispatch(tool_id, args, context)
