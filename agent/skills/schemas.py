# agent/skills/schemas.py
"""SkillSpec — skill metadata."""

from dataclasses import dataclass, field


@dataclass
class SkillSpec:
    skill_id: str = ""
    name: str = ""
    description: str = ""
    status: str = "disabled"  # enabled | disabled | planned
    related_tools: list = field(default_factory=list)
    prompt_summary: str = ""
    module_id: str = ""


# Built-in skill definitions
SKILL_CONFIG_TRANSLATION = SkillSpec(
    skill_id="config_translation",
    name="Config Translation",
    description="Translate network configuration between vendor formats",
    status="enabled",
    related_tools=["network.config.translate", "network.config.parse", "network.interface.extract"],
    prompt_summary="Use this skill to translate network device configuration. Requires source_config and target_vendor. Does not claim deployable_config is authoritative unless module validation generated it.",
    module_id="config_translation",
)

SKILL_ASSISTANT_CHAT = SkillSpec(
    skill_id="assistant_chat",
    name="Assistant Chat",
    description="General Q&A and network assistance",
    status="enabled",
    related_tools=[],
    prompt_summary="I am a network agent assistant. I can help with configuration translation, network queries, and general Q&A.",
    module_id="",
)

SKILL_KNOWLEDGE = SkillSpec(
    skill_id="knowledge_query",
    name="Knowledge Query",
    description="Query network documentation and knowledge base",
    status="enabled",
    related_tools=["knowledge.query", "knowledge.search"],
    prompt_summary="Use this skill to query local knowledge. Never fabricate sources. If no results are found, report honestly.",
    module_id="knowledge",
)

SKILL_TOPOLOGY = SkillSpec(
    skill_id="topology",
    name="Topology",
    description="Network topology analysis and visualization",
    status="planned",
    related_tools=[],
    prompt_summary="",
    module_id="topology",
)

SKILL_INSPECTION = SkillSpec(
    skill_id="inspection",
    name="Inspection",
    description="Network device inspection and health checks",
    status="planned",
    related_tools=[],
    prompt_summary="",
    module_id="inspection",
)

SKILL_CMDB = SkillSpec(
    skill_id="cmdb",
    name="CMDB",
    description="Configuration management database",
    status="planned",
    related_tools=[],
    prompt_summary="",
    module_id="cmdb",
)
