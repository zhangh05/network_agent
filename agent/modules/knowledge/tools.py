# agent/modules/knowledge/tools.py
"""Knowledge tools (v1.0) — registers the workspace knowledge store tools.

Six LLM-callable tools, all wrapping agent.modules.knowledge.service:
  - knowledge.query            (query)
  - knowledge.import_document  (import_document)
  - knowledge.list_sources     (list_sources)
  - knowledge.read_source      (read_source)
  - knowledge.disable_source   (disable_source)
  - knowledge.delete_source    (delete_source)

v0.8.2 result contract: every handler returns a dict that is
structurally a ToolResult (call_id / tool_id / ok / summary / content
/ data / artifacts / source_count / manual_review_count / errors /
warnings / metadata). Internally:
  service_fn(args) -> result dict
  -> service.to_module_result(result)         # business output
  -> ToolResult.from_module_result(...)        # runtime contract
"""

from agent.tools.schemas import ToolSpec


# ── ToolSpec declarations ──

TOOL_KNOWLEDGE_QUERY = ToolSpec(
    tool_id="knowledge.query",
    name="query",
    category="knowledge",
    description=(
        "Query the workspace knowledge store. Returns retrieved hits "
        "if available. Never fabricates sources or citations. If no "
        "results are found, reports honestly."
    ),
    risk_level="low",
    enabled=True,
    requires_approval=False,
    callable_by_llm=True,
    forbidden=False,
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query."},
            "top_k": {"type": "integer", "description": "Max results (default 5)."},
            "filters": {"type": "object", "description": "Optional filter criteria."},
        },
        "required": ["query"],
    },
    source="module:knowledge",
)


TOOL_KNOWLEDGE_IMPORT = ToolSpec(
    tool_id="knowledge.import_document",
    name="import_document",
    category="knowledge",
    description=(
        "Import a document into the workspace knowledge store. Returns "
        "a stable source_id. Does not fabricate sources; the caller "
        "supplies the content."
    ),
    risk_level="low",
    enabled=True,
    requires_approval=False,
    callable_by_llm=True,
    forbidden=False,
    input_schema={
        "type": "object",
        "properties": {
            "workspace_id": {"type": "string"},
            "title": {"type": "string"},
            "content": {"type": "string"},
            "source": {"type": "string"},
            "metadata": {"type": "object"},
        },
        "required": ["workspace_id", "title", "content"],
    },
    source="module:knowledge",
)


TOOL_KNOWLEDGE_LIST = ToolSpec(
    tool_id="knowledge.list_sources",
    name="list_sources",
    category="knowledge",
    description=(
        "List source records in the workspace knowledge store. Returns "
        "source_id / title / source / enabled / created_at / metadata. "
        "Does not return content or local storage paths."
    ),
    risk_level="low",
    enabled=True,
    requires_approval=False,
    callable_by_llm=True,
    forbidden=False,
    input_schema={
        "type": "object",
        "properties": {
            "workspace_id": {"type": "string"},
            "include_disabled": {"type": "boolean"},
            "include_deleted": {"type": "boolean"},
        },
        "required": ["workspace_id"],
    },
    source="module:knowledge",
)


TOOL_KNOWLEDGE_READ = ToolSpec(
    tool_id="knowledge.read_source",
    name="read_source",
    category="knowledge",
    description=(
        "Read full content + metadata of a single source. Returns "
        "ok=false when the source is missing or soft-deleted."
    ),
    risk_level="low",
    enabled=True,
    requires_approval=False,
    callable_by_llm=True,
    forbidden=False,
    input_schema={
        "type": "object",
        "properties": {
            "workspace_id": {"type": "string"},
            "source_id": {"type": "string"},
        },
        "required": ["workspace_id", "source_id"],
    },
    source="module:knowledge",
)


TOOL_KNOWLEDGE_DISABLE = ToolSpec(
    tool_id="knowledge.disable_source",
    name="disable_source",
    category="knowledge",
    description=(
        "Soft-disable a source. The record stays in storage but is "
        "excluded from query. Pass disabled=false to re-enable."
    ),
    risk_level="low",
    enabled=True,
    requires_approval=False,
    callable_by_llm=True,
    forbidden=False,
    input_schema={
        "type": "object",
        "properties": {
            "workspace_id": {"type": "string"},
            "source_id": {"type": "string"},
            "disabled": {"type": "boolean"},
        },
        "required": ["workspace_id", "source_id"],
    },
    source="module:knowledge",
)


TOOL_KNOWLEDGE_DELETE = ToolSpec(
    tool_id="knowledge.delete_source",
    name="delete_source",
    category="knowledge",
    description=(
        "Soft-delete a source. The record stays in storage with "
        "deleted=true; audit trail is kept. Hard delete is not "
        "exposed in v1.0."
    ),
    risk_level="low",
    enabled=True,
    requires_approval=False,
    callable_by_llm=True,
    forbidden=False,
    input_schema={
        "type": "object",
        "properties": {
            "workspace_id": {"type": "string"},
            "source_id": {"type": "string"},
        },
        "required": ["workspace_id", "source_id"],
    },
    source="module:knowledge",
)


# ── v0.8.2 tool handlers ──

def _build_handler(service_fn, tool_id_str: str,
                   passthrough_keys: tuple = ()):
    """Build a tool handler that:
      1. calls service_fn(**{k:v for k,v in args.items() if k in passthrough_keys})
      2. projects result dict to ModuleResult then to ToolResult
      3. returns the 10-standard-field dict (v0.8.2)
    """
    allowed = set(passthrough_keys)

    def _handler(args: dict, context=None) -> dict:
        from agent.modules.knowledge.service import to_module_result
        from agent.protocol.tool_result import ToolResult
        call_id = ""
        workspace_id = "default"
        if context:
            call_id = (getattr(context, "call_id", None)
                        or getattr(context, "tool_call_id", "")) or ""
            workspace_id = getattr(context, "workspace_id", workspace_id)
        kwargs = {k: v for k, v in (args or {}).items() if k in allowed}
        if "workspace_id" not in kwargs and workspace_id:
            kwargs["workspace_id"] = workspace_id
        try:
            result = service_fn(**kwargs)
        except Exception as e:
            result = {
                "ok": False,
                "summary": f"knowledge service raised: {e!r}",
                "errors": ["knowledge_service_raised"],
            }
        mr = to_module_result(result)
        tr = ToolResult.from_module_result(
            tool_id=tool_id_str,
            call_id=call_id,
            module_result=mr,
        )
        out = tr.to_dict()
        # Backward-compat top-level fields
        out["source_count"] = tr.source_count
        if "source_id" in result:
            out["source_id"] = result["source_id"]
        return out

    return _handler


from agent.modules.knowledge import service as _knowledge_service


tool_handler_query = _build_handler(
    _knowledge_service.query_knowledge, "knowledge.query",
    passthrough_keys=("query", "workspace_id", "top_k", "filters"),
)
tool_handler_import = _build_handler(
    _knowledge_service.import_document, "knowledge.import_document",
    passthrough_keys=("workspace_id", "title", "content", "source", "metadata"),
)
tool_handler_list = _build_handler(
    _knowledge_service.list_sources, "knowledge.list_sources",
    passthrough_keys=("workspace_id", "include_disabled", "include_deleted"),
)
tool_handler_read = _build_handler(
    _knowledge_service.read_source, "knowledge.read_source",
    passthrough_keys=("workspace_id", "source_id"),
)
tool_handler_disable = _build_handler(
    _knowledge_service.disable_source, "knowledge.disable_source",
    passthrough_keys=("workspace_id", "source_id", "disabled"),
)
tool_handler_delete = _build_handler(
    _knowledge_service.delete_source, "knowledge.delete_source",
    passthrough_keys=("workspace_id", "source_id"),
)


# Back-compat alias for v0.7.x callers
tool_handler = tool_handler_query
