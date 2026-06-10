# agent/tools/router.py
"""ToolRouter — centralized tool name mapping and dispatch."""

from agent.tools.schemas import LLMToolSpec
from agent.tools.registry import ToolRegistry
from agent.llm.tool_adapter import to_llm_tool_name, from_llm_tool_name
from agent.protocol.tool_call import ToolCall
from agent.protocol.tool_result import ToolResult


class UnknownToolCallError(Exception):
    """Raised when LLM attempts to call a tool not in model-visible whitelist."""
    pass


class ToolRouter:
    def __init__(self, registry: ToolRegistry = None):
        self.registry = registry or ToolRegistry()
        self.model_visible_specs: list = []
        self.llm_name_map: dict = {}  # llm_safe_name → real_tool_id
        self._build()

    def _build(self):
        visible = self.registry.list_model_visible()
        self.model_visible_specs = []
        self.llm_name_map = {}
        for spec in visible:
            llm_name = to_llm_tool_name(spec.tool_id)
            llm_spec = LLMToolSpec(
                name=llm_name,
                description=spec.description,
                parameters=spec.input_schema,
                real_tool_id=spec.tool_id,
            )
            self.model_visible_specs.append(llm_spec)
            self.llm_name_map[llm_name] = spec.tool_id

    @classmethod
    def from_turn_context(cls, context) -> "ToolRouter":
        if context and context.tool_router:
            return context.tool_router
        return cls()

    def model_visible_tools(self) -> list:
        """Return OpenAI-format tool definitions for LLM."""
        return [s.to_openai_function() for s in self.model_visible_specs]

    def build_tool_call(self, raw_llm_tool_call) -> ToolCall:
        """Convert raw LLM tool_call to ToolCall with real_tool_id.

        Validates that the LLM tool name is in the model-visible whitelist.
        Raises UnknownToolCallError if the tool is not exposed to the model.
        """
        llm_name = raw_llm_tool_call.name if hasattr(raw_llm_tool_call, 'name') else raw_llm_tool_call.get("name", "")

        # Whitelist check: only allow tools that were explicitly exposed to LLM
        if llm_name not in self.llm_name_map:
            raise UnknownToolCallError(f"Tool not visible to model: {llm_name}")

        call_id = raw_llm_tool_call.id if hasattr(raw_llm_tool_call, 'id') else raw_llm_tool_call.get("id", "")
        args = raw_llm_tool_call.arguments if hasattr(raw_llm_tool_call, 'arguments') else raw_llm_tool_call.get("arguments", {})

        if isinstance(args, str):
            import json
            try:
                args = json.loads(args)
            except Exception:
                args = {"raw": args}

        real_tool_id = self.llm_name_map[llm_name]
        tc = ToolCall(
            call_id=call_id,
            llm_tool_name=llm_name,
            real_tool_id=real_tool_id,
            arguments=args,
        )
        return tc

    def dispatch(self, tool_call: ToolCall, context=None) -> ToolResult:
        """Execute tool call and return ToolResult."""
        try:
            raw = self.registry.dispatch(tool_call.real_tool_id, tool_call.arguments, context)
            return ToolResult(
                call_id=tool_call.call_id,
                tool_id=tool_call.real_tool_id,
                ok=raw.get("ok", False),
                summary=raw.get("summary", ""),
                content=str(raw)[:2000],
                errors=raw.get("errors", []),
                warnings=raw.get("warnings", []),
                raw=raw,
            )
        except Exception as e:
            return ToolResult(
                call_id=tool_call.call_id,
                tool_id=tool_call.real_tool_id,
                ok=False,
                summary=str(e)[:200],
                errors=[str(e)[:200]],
            )
