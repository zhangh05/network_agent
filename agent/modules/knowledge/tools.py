# agent/modules/knowledge/tools.py
"""Knowledge Query tool — registers knowledge.query as a runtime tool.

This tool wraps the knowledge service.
It does NOT fabricate sources, scores, or citations.
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

    Called by ToolRegistry.dispatch().
    """
    from agent.modules.knowledge.service import query_knowledge

    query = args.get("query", "")
    top_k = args.get("top_k", 5)
    filters = args.get("filters")

    workspace_id = "default"
    if context:
        workspace_id = getattr(context, "workspace_id", workspace_id)

    result = query_knowledge(
        query=query,
        workspace_id=workspace_id,
        top_k=top_k,
        filters=filters,
    )

    return {
        "ok": result["ok"],
        "summary": result.get("summary", ""),
        "content": {
            "hits": result.get("hits", []),
            "source_count": result.get("source_count", 0),
            "source_summary": result.get("source_summary", []),
            "query": result.get("query", ""),
        },
        "source_count": result.get("source_count", 0),
        "errors": result.get("errors", []),
        "warnings": result.get("warnings", []),
        "metadata": result.get("metadata", {}),
    }
