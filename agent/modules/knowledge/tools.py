# agent/modules/knowledge/tools.py
"""Knowledge tools (v1.0.1) — 12 LLM-callable tools total.

v1.0 (kept for compatibility, 6 tools):
  - knowledge.query
  - knowledge.import_document
  - knowledge.list_sources
  - knowledge.read_source
  - knowledge.disable_source
  - knowledge.delete_source

v1.0.1 (new, 6 tools):
  - knowledge.import.file
  - knowledge.chunk.list
  - knowledge.search
  - knowledge.read_chunk
  - knowledge.read_parent
  - knowledge.reindex_source

All handlers use the v0.8.2 ToolResult.from_module_result projection.
"""

from agent.tools.schemas import ToolSpec


# ── v1.0 ToolSpec declarations (kept verbatim) ──

TOOL_KNOWLEDGE_QUERY = ToolSpec(
    tool_id="knowledge.query",
    name="query",
    category="knowledge",
    description=(
        "High-level knowledge query. Internally: search_chunks + "
        "read_parent expansion. Returns top child chunks plus a "
        "per-hit parent snippet. Never fabricates sources."
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
        "Import raw text into the workspace knowledge store. v1.0 "
        "raw-text import; for files use knowledge.import_file."
    ),
    risk_level="low",
    enabled=True,
    requires_approval=False,
    callable_by_llm=True,
    forbidden=False,
    input_schema={
        "type": "object",
        "properties": {
            "workspace_id": {"type": "string", "description": "Workspace id."},
            "title": {"type": "string", "description": "Document title."},
            "content": {"type": "string", "description": "Document text content."},
            "source": {"type": "string", "description": "Source origin label, e.g. web, manual."},
            "metadata": {"type": "object", "description": "Optional key-value metadata."},
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
        "List source records in the workspace knowledge store. v1.0 "
        "surface; for chunked view use knowledge.list_chunks."
    ),
    risk_level="low",
    enabled=True,
    requires_approval=False,
    callable_by_llm=True,
    forbidden=False,
    input_schema={
        "type": "object",
        "properties": {
            "workspace_id": {"type": "string", "description": "Workspace id."},
            "include_disabled": {"type": "boolean", "description": "Include disabled sources."},
            "include_deleted": {"type": "boolean", "description": "Include soft-deleted sources."},
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
        "Read full content + metadata of a single source. "
        "Returns title, source_type, status, sensitivity, "
        "and full content body."
    ),
    risk_level="low",
    enabled=True,
    requires_approval=False,
    callable_by_llm=True,
    forbidden=False,
    input_schema={
        "type": "object",
        "properties": {
            "workspace_id": {"type": "string", "description": "Workspace id."},
            "source_id": {"type": "string", "description": "Knowledge source id."},
        },
        "required": ["workspace_id", "source_id"],
    },
    source="module:knowledge",
)


TOOL_KNOWLEDGE_DISABLE = ToolSpec(
    tool_id="knowledge.disable_source",
    name="disable_source",
    category="knowledge",
    description="Soft-disable a source. Pass disabled=false to re-enable.",
    risk_level="low",
    enabled=True,
    requires_approval=False,
    callable_by_llm=True,
    forbidden=False,
    input_schema={
        "type": "object",
        "properties": {
            "workspace_id": {"type": "string", "description": "Workspace id."},
            "source_id": {"type": "string", "description": "Knowledge source id."},
            "disabled": {"type": "boolean", "description": "Set true to disable, false to re-enable."},
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
        "Soft-delete a source. v1.0.1 also drops the source's chunks."
    ),
    risk_level="low",
    enabled=True,
    requires_approval=False,
    callable_by_llm=True,
    forbidden=False,
    input_schema={
        "type": "object",
        "properties": {
            "workspace_id": {"type": "string", "description": "Workspace id."},
            "source_id": {"type": "string", "description": "Knowledge source id."},
        },
        "required": ["workspace_id", "source_id"],
    },
    source="module:knowledge",
)


# ── v1.0.1 ToolSpec declarations (6 new) ──

TOOL_KNOWLEDGE_IMPORT_FILE = ToolSpec(
    tool_id="knowledge.import_file",
    name="import_file",
    category="knowledge",
    description=(
        "Import a file (md / txt / html / docx / text-pdf). Parses, "
        "chunks (parent / child), builds BM25 index. Scanned PDFs "
        "return ok=false with error=unsupported_ocr."
    ),
    risk_level="low",
    enabled=True,
    requires_approval=False,
    callable_by_llm=True,
    forbidden=False,
    input_schema={
        "type": "object",
        "properties": {
            "workspace_id": {"type": "string", "description": "Workspace id."},
            "file_path": {"type": "string",
                           "description": "Path to a local file."},
            "title": {"type": "string"},
            "author": {"type": "string", "description": "Document author name."},
            "edition": {"type": "string", "description": "Document edition/version."},
            "source_type": {
                "type": "string",
                "enum": ["book", "manual", "rfc", "project_doc", "attachment", "memory"],
            },
            "scope": {
                "type": "string",
                "enum": ["global", "workspace", "session"],
            },
            "language": {"type": "string", "description": "Document language code, e.g. zh-CN."},
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of tag strings.",
            },
            "metadata": {"type": "object"},
        },
        "required": ["workspace_id", "file_path"],
    },
    source="module:knowledge",
)


TOOL_KNOWLEDGE_LIST_CHUNKS = ToolSpec(
    tool_id="knowledge.list_chunks",
    name="list_chunks",
    category="knowledge",
    description=(
        "List chunks in a workspace. Filter by source_id and "
        "chunk_type (parent / child). Returns lightweight view (no "
        "full content)."
    ),
    risk_level="low",
    enabled=True,
    requires_approval=False,
    callable_by_llm=True,
    forbidden=False,
    input_schema={
        "type": "object",
        "properties": {
            "workspace_id": {"type": "string", "description": "Workspace id."},
            "source_id": {"type": "string", "description": "Knowledge source id."},
            "chunk_type": {
                "type": "string",
                "enum": ["parent", "child"],
            },
            "limit": {"type": "integer", "description": "Max items to return.", "default": 10},
        },
        "required": ["workspace_id"],
    },
    source="module:knowledge",
)


TOOL_KNOWLEDGE_SEARCH_CHUNKS = ToolSpec(
    tool_id="knowledge.search",
    name="search_chunks",
    category="knowledge",
    description=(
        "BM25 lexical search over child chunks. Returns hits with "
        "score / lexical_score / semantic_score / final_score / scope. "
        "Does NOT return full content; use knowledge.read_chunk or "
        "knowledge.read_parent for that."
    ),
    risk_level="low",
    enabled=True,
    requires_approval=False,
    callable_by_llm=True,
    forbidden=False,
    input_schema={
        "type": "object",
        "properties": {
            "workspace_id": {"type": "string", "description": "Workspace id."},
            "query": {"type": "string", "description": "Search query text."},
            "top_k": {"type": "integer", "description": "Max results.", "default": 5},
            "scope": {
                "type": "string",
                "enum": ["global", "workspace", "session"],
            },
            "source_id": {"type": "string", "description": "Knowledge source id."},
            "source_type": {"type": "string", "description": "Filter by source type, e.g. documentation."},
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of tag strings to filter on.",
            },
            "chapter": {"type": "string", "description": "Filter by chapter/section name."},
        },
        "required": ["workspace_id", "query"],
    },
    source="module:knowledge",
)


TOOL_KNOWLEDGE_READ_CHUNK = ToolSpec(
    tool_id="knowledge.read_chunk",
    name="read_chunk",
    category="knowledge",
    description=(
        "Read a single chunk's full content + metadata. Returns "
        "ok=false when missing."
    ),
    risk_level="low",
    enabled=True,
    requires_approval=False,
    callable_by_llm=True,
    forbidden=False,
    input_schema={
        "type": "object",
        "properties": {
            "workspace_id": {"type": "string", "description": "Workspace id."},
            "chunk_id": {"type": "string", "description": "Knowledge chunk id."},
        },
        "required": ["workspace_id", "chunk_id"],
    },
    source="module:knowledge",
)


TOOL_KNOWLEDGE_READ_PARENT = ToolSpec(
    tool_id="knowledge.read_parent",
    name="read_parent",
    category="knowledge",
    description=(
        "Read the parent chunk of a child chunk (chapter / section "
        "context)."
    ),
    risk_level="low",
    enabled=True,
    requires_approval=False,
    callable_by_llm=True,
    forbidden=False,
    input_schema={
        "type": "object",
        "properties": {
            "workspace_id": {"type": "string", "description": "Workspace id."},
            "child_chunk_id": {"type": "string", "description": "Child chunk id to read parent of."},
        },
        "required": ["workspace_id", "child_chunk_id"],
    },
    source="module:knowledge",
)


TOOL_KNOWLEDGE_REINDEX = ToolSpec(
    tool_id="knowledge.reindex_source",
    name="reindex_source",
    category="knowledge",
    description=(
        "Rebuild the parent / child chunks for an existing source. "
        "The source record is not modified."
    ),
    risk_level="low",
    enabled=True,
    requires_approval=False,
    callable_by_llm=True,
    forbidden=False,
    input_schema={
        "type": "object",
        "properties": {
            "workspace_id": {"type": "string", "description": "Workspace id."},
            "source_id": {"type": "string", "description": "Knowledge source id."},
        },
        "required": ["workspace_id", "source_id"],
    },
    source="module:knowledge",
)


# ── v0.8.2 tool handlers ──

def _build_handler(service_fn, tool_id_str: str,
                   passthrough_keys: tuple = (),
                   extract_path_key: str = ""):
    """Build a tool handler that:
      1. extracts file_path from args if needed (key remapping)
      2. calls service_fn(**{k:v for k,v in args.items() if k in passthrough_keys})
      3. projects result dict to ModuleResult then to ToolResult
      4. returns the 10-standard-field dict (v0.8.2)
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
        # Map file_path -> source for import_file
        if extract_path_key and extract_path_key in kwargs:
            kwargs["source"] = kwargs.pop(extract_path_key)
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
        out["source_count"] = tr.source_count
        if "source_id" in result:
            out["source_id"] = result["source_id"]
        if "chunk_id" in result:
            out["chunk_id"] = result["chunk_id"]
        if "parent_chunk_id" in result:
            out["parent_chunk_id"] = result["parent_chunk_id"]
        if "chunk_count" in result:
            out["chunk_count"] = result["chunk_count"]
        if "parent_count" in result:
            out["parent_count"] = result["parent_count"]
        if "format" in result:
            out["format"] = result["format"]
        if "source_type" in result:
            out["source_type"] = result["source_type"]
        return out

    return _handler


from agent.modules.knowledge import service as _knowledge_service


# v1.0 handlers
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

# v1.0.1 handlers
tool_handler_import_file = _build_handler(
    _knowledge_service.import_file, "knowledge.import_file",
    passthrough_keys=("workspace_id", "source", "title", "author",
                       "edition", "source_type", "scope", "language",
                       "tags", "metadata"),
    extract_path_key="file_path",
)
tool_handler_list_chunks = _build_handler(
    _knowledge_service.list_chunks, "knowledge.list_chunks",
    passthrough_keys=("workspace_id", "source_id", "chunk_type", "limit"),
)
tool_handler_search_chunks = _build_handler(
    _knowledge_service.search_chunks, "knowledge.search",
    passthrough_keys=("workspace_id", "query", "top_k", "scope",
                       "source_id", "source_type", "tags", "chapter"),
)
tool_handler_read_chunk = _build_handler(
    _knowledge_service.read_chunk, "knowledge.read_chunk",
    passthrough_keys=("workspace_id", "chunk_id"),
)
tool_handler_read_parent = _build_handler(
    _knowledge_service.read_parent, "knowledge.read_parent",
    passthrough_keys=("workspace_id", "child_chunk_id"),
)
tool_handler_reindex = _build_handler(
    _knowledge_service.reindex_source, "knowledge.reindex_source",
    passthrough_keys=("workspace_id", "source_id"),
)


# Back-compat alias for v0.7.x callers
tool_handler = tool_handler_query
