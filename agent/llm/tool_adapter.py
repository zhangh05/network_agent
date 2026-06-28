# agent/llm/tool_adapter.py
"""Tool adapter — convert ToolSpec to OpenAI function-calling format.

Tool name mapping for LLM function calling:
- LLM function names cannot contain dots (`.`)
- Convert `.` → `__` for LLM-safe names
- Convert `__` → `.` when mapping back to real tool_id

v3.0: the LLM-facing surface is canonical-only. The function name
and the description prefix both reference the canonical tool_id;
internal dispatch fields are never exposed to the model.
"""

from typing import List


def to_llm_tool_name(tool_id: str) -> str:
    """Convert tool_id to LLM-safe function name.

    Examples:
        "system.manage" -> "runtime__health"
        "web.manage" -> "web__search"
        "artifact_list" -> "artifact_list"  (no dots, no change)
    """
    return tool_id.replace(".", "__")


def from_llm_tool_name(llm_name: str) -> str:
    """Convert LLM-safe function name back to real tool_id.

    Examples:
        "runtime__health" -> "system.manage"
        "web__search" -> "web.manage"
        "artifact_list" -> "artifact_list"  (no double underscore, no change)
    """
    return llm_name.replace("__", ".")


def tool_spec_to_openai_function(tool: dict) -> dict:
    """Convert a single ToolSpec dict to OpenAI function definition.

    v3.0 canonical-only: the description prefix carries only the
    canonical tool_id. Internal dispatch fields are stripped before
    this runs.
    """
    metadata = tool.get("metadata") or {}
    canonical_tool_id = (
        tool.get("canonical_tool_id")
        or metadata.get("canonical_tool_id")
        or tool.get("tool_id", "")
    )
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
            param["description"] = str(prop.get("description", ""))[:200]
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
    llm_name = to_llm_tool_name(canonical_tool_id)
    description = (tool.get("description") or tool.get("name") or canonical_tool_id)[:420]
    description = f"[tool_id={canonical_tool_id}] {description}"[:512]

    return {
        "type": "function",
        "function": {
            "name": llm_name,
            "description": description,
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
    from agent.runtime.services import default_runtime_services
    services = default_runtime_services()
    raw = []
    for spec in services.tool_service.registry.list_model_visible():
        raw.append({
            "tool_id": spec.tool_id,
            "name": spec.name,
            "description": spec.description,
            "risk_level": spec.risk_level,
            "enabled": spec.enabled,
            "input_schema": spec.input_schema,
            "metadata": getattr(spec, "metadata", {}) or {},
            **(getattr(spec, "metadata", {}) or {}),
        })
    return build_tool_registry_for_llm(raw)
