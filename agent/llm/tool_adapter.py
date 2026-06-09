# agent/llm/tool_adapter.py
"""Tool adapter — convert ToolSpec to OpenAI function-calling format."""

from typing import List


def tool_spec_to_openai_function(tool: dict) -> dict:
    """Convert a single ToolSpec dict to OpenAI function definition."""
    schema = tool.get("input_schema") or {}
    properties = schema.get("properties", {})
    required = schema.get("required", [])

    params_def = {
        "type": "object",
        "properties": {},
        "required": required,
    }

    for name, prop in properties.items():
        param = {"type": prop.get("type", "string")}
        if prop.get("description"):
            param["description"] = str(prop["description"])[:200]
        if "enum" in prop:
            param["enum"] = prop["enum"]
        if "default" in prop:
            param["default"] = prop["default"]
        params_def["properties"][name] = param

    if not params_def["properties"]:
        params_def.pop("properties")
    if not params_def.get("required"):
        params_def.pop("required")

    return {
        "type": "function",
        "function": {
            "name": tool["tool_id"],
            "description": (tool.get("description") or tool.get("name") or tool["tool_id"])[:512],
            "parameters": params_def,
        },
    }


def build_tool_registry_for_llm(tools: List[dict]) -> List[dict]:
    """Build OpenAI-format tool definitions from ToolSpec dicts.

    Excludes forbidden tools and optionally disabled tools.
    Returns a list ready to pass as LLMRequest.tools.
    """
    result = []
    for tool in tools:
        if tool.get("risk_level") == "forbidden":
            continue
        if not tool.get("enabled", True):
            continue
        result.append(tool_spec_to_openai_function(tool))
    return result


def list_tools_for_orchestrator() -> List[dict]:
    """Get all enabled, non-forbidden tools as OpenAI function definitions.

    Returns the full list suitable for the LLM orchestrator's system context.
    """
    from tool_runtime.integration import get_default_tool_runtime_client
    client = get_default_tool_runtime_client()
    raw = client.list_tools()
    return build_tool_registry_for_llm(raw)


def build_system_prompt_with_tools(workspace_id: str = "default") -> str:
    """Build the system prompt that tells the LLM about available tools."""
    tools = list_tools_for_orchestrator()

    prompt = f"""You are Network Agent, a network-engineering AI assistant. You have {len(tools)} tools available via function calling.

How to use tools:
- For web search or real-time info: use web.search, web.fetch_summary
- For system status: use runtime.health, runtime.selfcheck, runtime.diagnostics
- For artifacts/files: use artifact.list, artifact.read_summary, artifact.search
- For knowledge base: use knowledge.search
- For sessions/runs: use session.list, run.list_recent
- Choose the right tool based on the user's request. Don't guess — use tools when needed.

Style:
- Answer in Chinese for Chinese-speaking users.
- Be concise. Don't repeat tool names in your answer.
- If a tool returns useful data, summarize it clearly. If it fails, suggest alternatives.
- Use the conversation history for context — if the user refers to something said earlier, use that context.
- NEVER claim to execute commands on real devices. NEVER output secrets.

Workspace: {workspace_id}"""

    return prompt
