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
            "query_knowledge",
            "import_document", "list_sources",
            "read_source", "disable_source", "delete_source",
        ],
        description=(
            "Workspace knowledge store. Service exposes "
            "{query_knowledge, import_document, list_sources, "
            "read_source, disable_source, delete_source}. snippet "
            "<= 200 chars; no hits => source_summary == []; "
            "score is a transparent token-overlap function (not a "
            "vector similarity model)."
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
            ],
            intent_patterns=[
                "查知识库", "查询资料", "RAG", "检索文档",
                "根据资料回答", "查一下之前的内容",
                "导入资料", "导入文档", "查看来源", "查看知识源",
                "禁用来源", "删除来源", "知识库管理",
                "search knowledge", "lookup docs",
                "import document", "list sources",
            ],
            required_inputs=[],
            prompt_summary=(
                "Use knowledge_query when the user asks to search, import, "
                "list, read, disable, or delete a knowledge source. "
                "Always read source content via knowledge.read_source; "
                "do not fabricate. If query returns no hits, say so "
                "honestly and suggest importing more material via "
                "knowledge.import_document."
            ),
            preconditions=[
                "User must provide a query OR a workspace_id.",
                "source_id must be valid for read / disable / delete.",
            ],
            postconditions=[
                "After import: list_sources shows the new source.",
                "After disable: query excludes the source.",
                "After delete: read_source returns None.",
                "Empty results always report honestly (no fabrication).",
            ],
            safety_rules=[
                "Never fabricate source, citation, score, or title.",
                "If knowledge store is unavailable, say so explicitly.",
                "score is a deterministic token-overlap value; do not "
                "re-rank or invent additional sources.",
                "Never expose local storage paths in user-visible output.",
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
            "Hits and source_summary are derived only from real "
            "knowledge store content; the capability never invents "
            "sources, citations, scores, or titles. Local storage "
            "paths are sanitized before being returned."
        ),
    ),
    dependencies=[],
    metadata={
        "version": "1.0",
        "owners": ["agent_backend"],
        "storage": "workspace/{workspace_id}/knowledge/sources.jsonl",
    },
)
