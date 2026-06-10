# agent/modules/knowledge/capability.py
"""Capability manifest for knowledge (RAG query).

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


CAPABILITY_KNOWLEDGE = CapabilityManifest(
    capability_id="knowledge",
    name="Knowledge / RAG",
    status="enabled",
    description=(
        "Query the local knowledge/RAG store. Returns retrieved hits and "
        "a source_summary. NEVER fabricates sources, citations, scores, "
        "or document titles."
    ),
    module=CapabilityModuleSpec(
        module_id="knowledge",
        status="enabled",
        service_path="agent.modules.knowledge.service",
        operations=["query_knowledge"],
        description=(
            "Local RAG query service. Returns "
            "{ok, summary, query, hits, source_count, source_summary, "
            "warnings, errors, metadata}. snippet <= 200 chars; "
            "no hits => source_summary == []."
        ),
    ),
    skills=[
        CapabilitySkillSpec(
            skill_id="knowledge_query",
            status="enabled",
            related_tools=["knowledge.query"],
            intent_patterns=[
                "查知识库",
                "查询资料",
                "RAG",
                "检索文档",
                "根据资料回答",
                "查一下之前的内容",
                "search knowledge",
                "lookup docs",
            ],
            required_inputs=["query"],
            prompt_summary=(
                "Use knowledge_query when the user asks to search local "
                "knowledge or project documents. Do not fabricate sources; "
                "answer only from returned hits/source_summary."
            ),
            preconditions=["User must provide a query."],
            postconditions=[
                "Summarize source_summary when hits exist.",
                "Say no relevant knowledge was found when hits are empty.",
            ],
            safety_rules=[
                "Never fabricate source, citation, score, or document title.",
                "If knowledge store is unavailable, say so explicitly.",
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
            handler_ref="agent.modules.knowledge.tools:tool_handler",
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
            description=(
                "Query the local knowledge/RAG store. Returns retrieved "
                "sources if available. Never fabricates sources or "
                "citations. If no results are found, reports honestly."
            ),
        ),
    ],
    outputs=[
        CapabilityOutputSpec(
            output_id="hits",
            output_type="hits",
            description="Raw hit list from the local RAG store.",
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
    ],
    safety=CapabilitySafetySpec(
        real_device_access=False,
        allows_config_push=False,
        produces_deployable_config=False,
        may_fabricate_sources=False,
        requires_human_review=False,
        notes=(
            "Hits and source_summary are derived only from real knowledge "
            "store results; the capability never invents sources."
        ),
    ),
    dependencies=[],
    metadata={
        "version": "0.7.1",
        "owners": ["agent_backend"],
    },
)
