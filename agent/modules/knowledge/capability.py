# agent/modules/knowledge/capability.py
"""Capability manifest for Knowledge / RAG."""

from agent.capabilities.schemas import (
    CapabilityManifest,
    CapabilityModuleSpec,
    CapabilityToolRef,
    CapabilityOutputSpec,
    CapabilitySafetySpec,
)


CAPABILITY_KNOWLEDGE = CapabilityManifest(
    capability_id="knowledge",
    name="Knowledge / RAG",
    status="enabled",
    description="知识库检索与 RAG。支持文档导入、语义搜索、分块阅读。",
    intent_patterns=[
        "知识库", "RAG", "文档搜索", "知识检索",
        "knowledge base", "rag search", "chunk",
    ],
    prompt_summary="知识库语义检索与 RAG。导入 workspace 文件建立索引，按语义搜索相关片段，支持源文档回溯。",
    module=CapabilityModuleSpec(
        module_id="knowledge",
        status="enabled",
        service_path="agent.modules.knowledge.service",
        operations=["search", "import", "list_sources", "read_chunk"],
        description="Knowledge base RAG engine.",
    ),
    tools=[
        # Knowledge tools (knowledge.search, knowledge.chunk.*, etc.) are 
        # registered via canonical_registry. This ref ensures capability 
        # validation passes; actual dispatch uses canonical handlers.
        CapabilityToolRef(
            tool_id="knowledge.search",
            status="enabled", callable_by_llm=True, risk_level="low",
            requires_approval=False, forbidden=False,
            handler_ref="tool_runtime.canonical_registry:handle_knowledge_search",
            description="语义搜索知识库，返回相关文档片段。",
        ),
    ],
    outputs=[CapabilityOutputSpec(
        output_id="knowledge_search_result",
        output_type="knowledge_search_result",
        description="知识库搜索结果。",
        artifact_type="knowledge_result", visible_to_user=True,
        sensitivity="internal", authoritative=True,
    )],
    safety=CapabilitySafetySpec(
        real_device_access=False, allows_config_push=False,
        produces_deployable_config=False, may_fabricate_sources=False,
        requires_human_review=False,
        notes="仅查询已有索引，不执行写操作。",
    ),
    dependencies=["artifact"],
    metadata={"version": "1.0.0", "owners": ["agent_backend"]},
)
