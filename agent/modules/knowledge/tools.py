# agent/modules/knowledge/tools.py
"""Knowledge Query tool — registers knowledge.query as a runtime tool.

This tool wraps the knowledge service.
It does NOT fabricate sources, scores, or citations.

v0.8.2 result contract:
  tool_handler returns a dict that is **structurally a ToolResult**
  (call_id / tool_id / ok / summary / content / data / artifacts /
  source_count / manual_review_count / errors / warnings / metadata).
  Internally:
    query_knowledge(args) -> result dict
    -> service.to_module_result(result)         # business output
    -> ToolResult.from_module_result(...)        # runtime contract
"""

from agent.tools.schemas import ToolSpec


TOOL_KNOWLEDGE_QUERY = ToolSpec(
    tool_id="knowledge.query",
    name="query",
    category="knowledge",
    description=(
        "Query the local knowledge/RAG store. Returns retrieved sources if "
        "available. Never fabricates sources or citations. If no results are "
        "found, reports honestly."
    ),
    risk_level="low",
    enabled=True,
    requires_approval=False,
    callable_by_llm=True,
    forbidden=False,
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query for the knowledge store",
            },
            "top_k": {
                "type": "integer",
                "description": "Maximum number of results to return (default 5)",
            },
            "filters": {
                "type": "object",
                "description": "Optional filter criteria",
            },
        },
        "required": ["query"],
    },
    source="module:knowledge",
)


def tool_handler(args: dict, context=None) -> dict:
    """Handle knowledge.query tool invocations.

    v0.8.2: returns a dict that is structurally a ToolResult.
    """
    from agent.modules.knowledge.service import query_knowledge, to_module_result
    from agent.protocol.tool_result import ToolResult

    query = args.get("query", "")
    top_k = args.get("top_k", 5)
    filters = args.get("filters")

    workspace_id = "default"
    session_id = ""
    call_id = ""
    if context:
        workspace_id = getattr(context, "workspace_id", workspace_id)
        session_id = getattr(context, "session_id", session_id)
        call_id = getattr(context, "call_id", call_id) or getattr(context, "tool_call_id", "")

    # 1. Service call
    result = query_knowledge(
        query=query,
        workspace_id=workspace_id,
        top_k=top_k,
        filters=filters,
    )

    # 2. Project to ModuleResult (business output contract)
    mr = to_module_result(result)

    # 3. Project to ToolResult (runtime / LLM contract)
    tr = ToolResult.from_module_result(
        tool_id="knowledge.query",
        call_id=call_id,
        module_result=mr,
    )

    # 4. Return as a dict (the loop / registry expects a dict today)
    out = tr.to_dict()
    # Backward-compat top-level fields for v0.7.x consumers
    out["source_count"] = tr.source_count
    return out
