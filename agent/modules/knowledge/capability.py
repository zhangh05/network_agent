# agent/modules/knowledge/capability.py
"""Capability manifest for knowledge (RAG + workspace knowledge store).

v1.0 — adds the workspace knowledge store surface:
  - knowledge.import_document
  - knowledge.list_sources
  - knowledge.read_source
  - knowledge.disable_source
  - knowledge.delete_source
  - knowledge.query     (kept from v0.7.1, now backed by the new store)

This is the single source of truth for the knowledge capability.
"""

from agent.capabilities.schemas import (
    CapabilityManifest,
    CapabilityModuleSpec,
    CapabilitySkillSpec,
    CapabilityToolRef,
    CapabilityOutputSpec,
    CapabilitySafetySpec,
)


# Common tool description fragments
_QUERY_DESC = (
    "Query the local knowledge/RAG store. Returns retrieved sources if "
    "available. Never fabricates sources or citations. If no results are "
    "found, reports honestly."
)


def _query_schema():
    return {
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
    }


CAPABILITY_KNOWLEDGE = CapabilityManifest(
    capability_id="knowledge",
    name="Knowledge / RAG",
    status="enabled",
    description=(
        "v1.0: full workspace knowledge store. Import documents, list "
        "sources, read source content, soft-disable / soft-delete "
        "sources, and query. Backed by a local JSONL store "
        "({ws_root}/{workspace_id}/knowledge/sources.jsonl). "
        "NEVER fabricates sources, citations, scores, or titles. "
        "The legacy context.knowledge_loader is consulted ONLY when "
        "the workspace store is empty (preserves v0.7.1 tests)."
    ),
    module=CapabilityModuleSpec(
        module_id="knowledge",
        status="enabled",
        service_path="agent.modules.knowledge.service",
        operations=[
            "query_knowledge",                          # v1.0.1 wrapper
            "import_document", "list_sources",          # v1.0 raw text
            "read_source", "disable_source",
            "delete_source",
            "import_file",                              # v1.0.1 ingestion
            "list_chunks", "search_chunks",             # v1.0.1 retrieval
            "read_chunk", "read_parent",
            "reindex_source",
        ],
        description=(
            "v1.0.1: workspace knowledge store + parent/child chunking + "
            "BM25 lexical index + scope-aware retrieval + parent "
            "expansion. Supports md / txt / html / docx / text-pdf "
            "ingestion; scanned PDFs return unsupported_ocr. Service "
            "exposes {query_knowledge, import_document, list_sources, "
            "read_source, disable_source, delete_source, import_file, "
            "list_chunks, search_chunks, read_chunk, read_parent, "
            "reindex_source}. Score metadata records "
            "lexical_score / semantic_score=null / final_score / "
            "scoring_version. No fabrication."
        ),
    ),
    skills=[
        CapabilitySkillSpec(
            skill_id="knowledge_query",
            status="enabled",
            related_tools=[
                "knowledge.query",
                "knowledge.import_document",
                "knowledge.list_sources",
                "knowledge.read_source",
                "knowledge.disable_source",
                "knowledge.delete_source",
                "knowledge.import_file",
                "knowledge.list_chunks",
                "knowledge.search_chunks",
                "knowledge.read_chunk",
                "knowledge.read_parent",
                "knowledge.reindex_source",
            ],
            intent_patterns=[
                "查知识库", "查询资料", "RAG", "检索文档",
                "根据资料回答", "查一下之前的内容",
                "导入资料", "导入文档", "查看来源", "查看知识源",
                "禁用来源", "删除来源", "知识库管理",
                "search knowledge", "lookup docs",
                "import document", "list sources",
                "导入书籍", "导入RFC", "导入手册", "导入项目文档",
                "查某本书", "查某章节", "查第 N 页",
                "查看命中原文", "查看整段上下文",
                "重建索引",
                "import book", "import rfc", "import manual",
                "look up chapter", "show full paragraph",
                "reindex",
            ],
            required_inputs=[],
            prompt_summary=(
                "Use knowledge_query for all knowledge operations. "
                "For raw text use knowledge.import_document; for files "
                "(md/txt/html/docx/text-pdf) use knowledge.import_file. "
                "For retrieval, prefer knowledge.query (high-level) or "
                "knowledge.search_chunks + knowledge.read_parent for "
                "section-level context. If query returns no hits, say "
                "so honestly and suggest importing more material."
            ),
            preconditions=[
                "User must provide a query OR a workspace_id.",
                "source_id must be valid for read / disable / delete.",
                "file_path must exist for import_file.",
            ],
            postconditions=[
                "After import: list_sources / list_chunks shows new entries.",
                "After disable: query / search_chunks excludes the source.",
                "After delete: read_source and read_chunk return not_found.",
                "Empty results always report honestly (no fabrication).",
            ],
            safety_rules=[
                "Never fabricate book / chapter / page / score / citation.",
                "If knowledge store is unavailable, say so explicitly.",
                "score is a deterministic BM25 token-overlap value; do not "
                "re-rank or invent additional chunks.",
                "Never expose local storage paths in user-visible output.",
                "Scanned PDFs must return unsupported_ocr; do not fake parse.",
            ],
        ),
    ],
    tools=[
        CapabilityToolRef(
            tool_id="knowledge.query",
            status="enabled",
            callable_by_llm=True,
            risk_level="low",
            requires_approval=False,
            forbidden=False,
            handler_ref="agent.modules.knowledge.tools:tool_handler_query",
            input_schema=_query_schema(),
            description=_QUERY_DESC,
        ),
        CapabilityToolRef(
            tool_id="knowledge.import_document",
            status="enabled",
            callable_by_llm=True,
            risk_level="low",
            requires_approval=False,
            forbidden=False,
            handler_ref="agent.modules.knowledge.tools:tool_handler_import",
            input_schema={
                "type": "object",
                "properties": {
                    "workspace_id": {"type": "string"},
                    "title": {"type": "string", "description": "Document title."},
                    "content": {"type": "string", "description": "Document content."},
                    "source": {"type": "string", "description": "Origin label."},
                    "metadata": {"type": "object", "description": "Optional metadata."},
                },
                "required": ["workspace_id", "title", "content"],
            },
            description=(
                "Import a document into the workspace knowledge store. "
                "Does not fabricate sources; the caller supplies the "
                "content. Returns source_id."
            ),
        ),
        CapabilityToolRef(
            tool_id="knowledge.list_sources",
            status="enabled",
            callable_by_llm=True,
            risk_level="low",
            requires_approval=False,
            forbidden=False,
            handler_ref="agent.modules.knowledge.tools:tool_handler_list",
            input_schema={
                "type": "object",
                "properties": {
                    "workspace_id": {"type": "string"},
                    "include_disabled": {"type": "boolean"},
                    "include_deleted": {"type": "boolean"},
                },
                "required": ["workspace_id"],
            },
            description=(
                "List source records in the workspace knowledge store. "
                "Returns source_id / title / source / enabled / "
                "created_at / metadata. Does not return content or "
                "local storage paths."
            ),
        ),
        CapabilityToolRef(
            tool_id="knowledge.read_source",
            status="enabled",
            callable_by_llm=True,
            risk_level="low",
            requires_approval=False,
            forbidden=False,
            handler_ref="agent.modules.knowledge.tools:tool_handler_read",
            input_schema={
                "type": "object",
                "properties": {
                    "workspace_id": {"type": "string"},
                    "source_id": {"type": "string"},
                },
                "required": ["workspace_id", "source_id"],
            },
            description=(
                "Read full content + metadata of a single source. "
                "Returns ok=false when the source is missing or "
                "soft-deleted."
            ),
        ),
        CapabilityToolRef(
            tool_id="knowledge.disable_source",
            status="enabled",
            callable_by_llm=True,
            risk_level="low",
            requires_approval=False,
            forbidden=False,
            handler_ref="agent.modules.knowledge.tools:tool_handler_disable",
            input_schema={
                "type": "object",
                "properties": {
                    "workspace_id": {"type": "string"},
                    "source_id": {"type": "string"},
                    "disabled": {"type": "boolean", "description": "True to disable, False to re-enable."},
                },
                "required": ["workspace_id", "source_id"],
            },
            description=(
                "Soft-disable a source. The record stays in storage but "
                "is excluded from query. Pass disabled=false to re-enable."
            ),
        ),
        CapabilityToolRef(
            tool_id="knowledge.delete_source",
            status="enabled",
            callable_by_llm=True,
            risk_level="low",
            requires_approval=False,
            forbidden=False,
            handler_ref="agent.modules.knowledge.tools:tool_handler_delete",
            input_schema={
                "type": "object",
                "properties": {
                    "workspace_id": {"type": "string"},
                    "source_id": {"type": "string"},
                },
                "required": ["workspace_id", "source_id"],
            },
            description=(
                "Soft-delete a source (record stays in storage with "
                "deleted=true; audit trail kept). Hard delete is not "
                "exposed in v1.0."
            ),
        ),
        # ── v1.0.1 new tools (6) ──
        CapabilityToolRef(
            tool_id="knowledge.import_file",
            status="enabled",
            callable_by_llm=True,
            risk_level="low",
            requires_approval=False,
            forbidden=False,
            handler_ref="agent.modules.knowledge.tools:tool_handler_import_file",
            input_schema={
                "type": "object",
                "properties": {
                    "workspace_id": {"type": "string"},
                    "file_path": {"type": "string",
                                   "description": "Path to a local file (md / txt / html / docx / text-pdf)."},
                    "title": {"type": "string"},
                    "author": {"type": "string"},
                    "edition": {"type": "string"},
                    "source_type": {
                        "type": "string",
                        "enum": ["book", "manual", "rfc", "project_doc", "attachment"],
                    },
                    "scope": {
                        "type": "string",
                        "enum": ["global", "workspace", "session"],
                    },
                    "language": {"type": "string"},
                    "tags": {"type": "object", "description": "List of tag strings."},
                    "metadata": {"type": "object"},
                },
                "required": ["workspace_id", "file_path"],
            },
            description=(
                "Import a file (md / txt / html / docx / text-pdf) into "
                "the workspace knowledge store, parse it, chunk it "
                "(parent / child), and build the BM25 index. Scanned "
                "PDFs return ok=false with error=unsupported_ocr."
            ),
        ),
        CapabilityToolRef(
            tool_id="knowledge.list_chunks",
            status="enabled",
            callable_by_llm=True,
            risk_level="low",
            requires_approval=False,
            forbidden=False,
            handler_ref="agent.modules.knowledge.tools:tool_handler_list_chunks",
            input_schema={
                "type": "object",
                "properties": {
                    "workspace_id": {"type": "string"},
                    "source_id": {"type": "string"},
                    "chunk_type": {
                        "type": "string",
                        "enum": ["parent", "child"],
                    },
                    "limit": {"type": "integer"},
                },
                "required": ["workspace_id"],
            },
            description=(
                "List chunks in a workspace. Filter by source_id and "
                "chunk_type (parent / child). Returns lightweight view "
                "(no full content)."
            ),
        ),
        CapabilityToolRef(
            tool_id="knowledge.search_chunks",
            status="enabled",
            callable_by_llm=True,
            risk_level="low",
            requires_approval=False,
            forbidden=False,
            handler_ref="agent.modules.knowledge.tools:tool_handler_search_chunks",
            input_schema={
                "type": "object",
                "properties": {
                    "workspace_id": {"type": "string"},
                    "query": {"type": "string"},
                    "top_k": {"type": "integer"},
                    "scope": {
                        "type": "string",
                        "enum": ["global", "workspace", "session"],
                    },
                    "source_id": {"type": "string"},
                    "source_type": {"type": "string"},
                    "tags": {"type": "object", "description": "List of tag strings."},
                    "chapter": {"type": "string"},
                },
                "required": ["workspace_id", "query"],
            },
            description=(
                "BM25 lexical search over child chunks. Returns hits "
                "with score / lexical_score / semantic_score / "
                "final_score / scope. Does NOT return full content; "
                "use knowledge.read_chunk or knowledge.read_parent for "
                "that."
            ),
        ),
        CapabilityToolRef(
            tool_id="knowledge.read_chunk",
            status="enabled",
            callable_by_llm=True,
            risk_level="low",
            requires_approval=False,
            forbidden=False,
            handler_ref="agent.modules.knowledge.tools:tool_handler_read_chunk",
            input_schema={
                "type": "object",
                "properties": {
                    "workspace_id": {"type": "string"},
                    "chunk_id": {"type": "string"},
                },
                "required": ["workspace_id", "chunk_id"],
            },
            description=(
                "Read a single chunk's full content + metadata. Returns "
                "ok=false when the chunk is missing."
            ),
        ),
        CapabilityToolRef(
            tool_id="knowledge.read_parent",
            status="enabled",
            callable_by_llm=True,
            risk_level="low",
            requires_approval=False,
            forbidden=False,
            handler_ref="agent.modules.knowledge.tools:tool_handler_read_parent",
            input_schema={
                "type": "object",
                "properties": {
                    "workspace_id": {"type": "string"},
                    "child_chunk_id": {"type": "string"},
                },
                "required": ["workspace_id", "child_chunk_id"],
            },
            description=(
                "Read the parent chunk of a child chunk. The parent "
                "represents the surrounding chapter / section context."
            ),
        ),
        CapabilityToolRef(
            tool_id="knowledge.reindex_source",
            status="enabled",
            callable_by_llm=True,
            risk_level="low",
            requires_approval=False,
            forbidden=False,
            handler_ref="agent.modules.knowledge.tools:tool_handler_reindex",
            input_schema={
                "type": "object",
                "properties": {
                    "workspace_id": {"type": "string"},
                    "source_id": {"type": "string"},
                },
                "required": ["workspace_id", "source_id"],
            },
            description=(
                "Rebuild the parent / child chunks for an existing "
                "source from its stored normalized_markdown. The source "
                "record itself is not modified."
            ),
        ),
    ],
    outputs=[
        CapabilityOutputSpec(
            output_id="hits",
            output_type="hits",
            description="Raw hit list from the workspace knowledge store.",
            artifact_type="",
            visible_to_user=True,
            sensitivity="internal",
            authoritative=False,
        ),
        CapabilityOutputSpec(
            output_id="source_summary",
            output_type="source_summary",
            description=(
                "Trimmed source summary derived from real hits. "
                "At most 5 entries; each snippet <= 200 chars. "
                "Empty when there are no hits."
            ),
            artifact_type="",
            visible_to_user=True,
            sensitivity="internal",
            authoritative=False,
        ),
        CapabilityOutputSpec(
            output_id="source_record",
            output_type="source_record",
            description="Source record (with or without content).",
            artifact_type="",
            visible_to_user=True,
            sensitivity="internal",
            authoritative=False,
        ),
    ],
    safety=CapabilitySafetySpec(
        real_device_access=False,
        allows_config_push=False,
        produces_deployable_config=False,
        may_fabricate_sources=False,
        requires_human_review=False,
        notes=(
            "v1.0.1: Hits and source_summary are derived only from "
            "real knowledge store content; the capability never invents "
            "sources, citations, scores, chapters, or page numbers. "
            "Local storage paths are sanitized. Scanned PDFs return "
            "unsupported_ocr; no fake parse."
        ),
    ),
    dependencies=[],
    metadata={
        "version": "1.0.1",
        "owners": ["agent_backend"],
        "storage": "workspace/{workspace_id}/knowledge/{sources.jsonl,chunks.jsonl,index.meta.json}",
    },
)
