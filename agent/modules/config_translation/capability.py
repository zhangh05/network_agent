# agent/modules/config_translation/capability.py
"""Capability manifest for config_translation.

This is the single source of truth for the config_translation capability.
ModuleRegistry / SkillRegistry / ToolRegistry / RuntimeSnapshot all derive
from this manifest. Editing capability behavior means editing this file.
"""

from agent.capabilities.schemas import (
    CapabilityManifest,
    CapabilityModuleSpec,
    CapabilitySkillSpec,
    CapabilityToolRef,
    CapabilityOutputSpec,
    CapabilitySafetySpec,
)


CAPABILITY_CONFIG_TRANSLATION = CapabilityManifest(
    capability_id="config_translation",
    name="Config Translation",
    status="enabled",
    description=(
        "Translate network device configuration between vendor formats "
        "(cisco / huawei / h3c / ruijie / juniper). Produces "
        "translated_config artifact and structured manual_review_items. "
        "Does NOT connect to real devices and does NOT push configuration."
    ),
    module=CapabilityModuleSpec(
        module_id="config_translation",
        status="enabled",
        service_path="agent.modules.config_translation.service",
        operations=["translate_config"],
        description=(
            "Structured config translation service. Returns "
            "{ok, summary, source_vendor, target_vendor, line_count, "
            "translated_config, manual_review_items, artifacts, warnings, "
            "errors, metadata}."
        ),
    ),
    skills=[
        CapabilitySkillSpec(
            skill_id="config_translation",
            status="enabled",
            related_tools=["config_translation.translate_config"],
            intent_patterns=[
                "配置翻译",
                "配置转换",
                "Cisco 转华为",
                "H3C 转华为",
                "ACL 转换",
                "interface 配置转换",
                "translate config",
                "convert config",
            ],
            required_inputs=["source_config", "target_vendor"],
            prompt_summary=(
                "Use config_translation when the user asks to translate or "
                "convert network device configuration between vendors. "
                "The output is translated_config, not authoritative "
                "deployable_config."
            ),
            preconditions=[
                "User must provide source configuration text.",
                "Target vendor must be known or requested from user.",
            ],
            postconditions=[
                "Mention translated_config artifact if generated.",
                "Mention manual_review_items if present.",
                "Do not claim the config is directly deployable.",
            ],
            safety_rules=[
                "Do not fabricate source_config.",
                "Do not claim direct device push.",
                "Do not mark translated_config as authoritative "
                "deployable_config.",
                "Human review is required when manual_review_items are present.",
            ],
        ),
    ],
    tools=[
        CapabilityToolRef(
            tool_id="config_translation.translate_config",
            status="enabled",
            callable_by_llm=True,
            risk_level="medium",
            requires_approval=False,
            forbidden=False,
            handler_ref="agent.modules.config_translation.tools:tool_handler",
            input_schema={
                "type": "object",
                "properties": {
                    "source_config": {
                        "type": "string",
                        "description": "Source network device configuration text",
                    },
                    "source_vendor": {
                        "type": "string",
                        "description": "Source vendor (auto|cisco|huawei|h3c|ruijie|juniper)",
                    },
                    "target_vendor": {
                        "type": "string",
                        "description": "Target vendor (e.g., huawei, cisco, h3c)",
                    },
                    "options": {
                        "type": "object",
                        "description": "Optional translation options",
                    },
                },
                "required": ["source_config", "target_vendor"],
            },
            description=(
                "Translate network device configuration between vendors. "
                "Requires source_config and target_vendor. Does not "
                "directly produce an authoritative deployable_config."
            ),
        ),
    ],
    outputs=[
        CapabilityOutputSpec(
            output_id="translated_config",
            output_type="translated_config",
            description="Translated configuration text (NOT deployable).",
            artifact_type="translated_config",
            visible_to_user=True,
            sensitivity="sensitive",
            authoritative=False,
            metadata={
                "deployable_config": False,
                "requires_human_review_when_review_items": True,
            },
        ),
        CapabilityOutputSpec(
            output_id="manual_review_items",
            output_type="manual_review_items",
            description=(
                "Structured list of human-review items. Each item carries "
                "severity / category / line_no / source_text / "
                "translated_text / reason / recommendation."
            ),
            artifact_type="",
            visible_to_user=True,
            sensitivity="internal",
            authoritative=False,
        ),
        CapabilityOutputSpec(
            output_id="translated_config_artifact",
            output_type="artifact",
            description="The translated_config persisted as an artifact.",
            artifact_type="translated_config",
            visible_to_user=True,
            sensitivity="sensitive",
            authoritative=False,
        ),
    ],
    safety=CapabilitySafetySpec(
        real_device_access=False,
        allows_config_push=False,
        produces_deployable_config=False,
        may_fabricate_sources=False,
        requires_human_review=True,
        notes=(
            "Translation result is never authoritative deployable_config; "
            "human review required when manual_review_items is non-empty."
        ),
    ),
    dependencies=[],
    metadata={
        "version": "0.7.1",
        "owners": ["agent_backend"],
    },
)
