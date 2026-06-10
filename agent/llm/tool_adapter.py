# agent/llm/tool_adapter.py
"""Tool adapter — convert ToolSpec to OpenAI function-calling format.

Tool name mapping for LLM function calling:
- LLM function names cannot contain dots (`.`)
- Convert `.` → `__` for LLM-safe names
- Convert `__` → `.` when mapping back to real tool_id
"""

from typing import List


def to_llm_tool_name(tool_id: str) -> str:
    """Convert tool_id to LLM-safe function name.
    
    Examples:
        "runtime.health" -> "runtime__health"
        "web.search" -> "web__search"
        "artifact_list" -> "artifact_list"  (no dots, no change)
    """
    return tool_id.replace(".", "__")


def from_llm_tool_name(llm_name: str) -> str:
    """Convert LLM-safe function name back to real tool_id.
    
    Examples:
        "runtime__health" -> "runtime.health"
        "web__search" -> "web.search"
        "artifact_list" -> "artifact_list"  (no double underscore, no change)
    """
    return llm_name.replace("__", ".") 


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

    # Use LLM-safe name (dots -> double underscore)
    llm_name = to_llm_tool_name(tool["tool_id"])

    return {
        "type": "function",
        "function": {
            "name": llm_name,
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
    """Build the system prompt that tells the LLM about available tools.
    
    Uses LLM-safe tool names (with __ instead of .).
    """
    tools = list_tools_for_orchestrator()
    
    # Build tool list with LLM-safe names
    tool_names = [t["function"]["name"] for t in tools[:30]]

    prompt = f"""You are Network Agent, a network-engineering AI assistant. You have {len(tools)} tools available via function calling.
    
How to use tools:
- For web search or real-time info: use the web__search function
- For system status: use runtime__health, runtime__selfcheck, runtime__diagnostics
- For artifacts/files: use artifact__list, artifact__read_summary, artifact__search
- For knowledge base: use knowledge__search
- For sessions/runs: use session__list, run__list_recent
- Choose the right tool based on the user's request. Don't guess — use tools when needed.

Style:
- Answer in Chinese for Chinese-speaking users.
- Be concise. Don't repeat tool names in your answer.
- If a tool returns useful data, summarize it clearly. If it fails, suggest alternatives.
- Use the conversation history for context — if the user refers to something said earlier, use that context.
- NEVER claim to execute commands on real devices. NEVER output secrets.

Workspace: {workspace_id}"""

    return prompt
