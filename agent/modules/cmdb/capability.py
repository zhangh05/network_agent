# agent/modules/cmdb/capability.py
"""Capability manifest for cmdb (PLANNED — NOT callable)."""

from agent.capabilities.schemas import (
    CapabilityManifest,
    CapabilityModuleSpec,
    CapabilitySkillSpec,
    CapabilityToolRef,
    CapabilityOutputSpec,
    CapabilitySafetySpec,
)


CAPABILITY_CMDB = CapabilityManifest(
    capability_id="cmdb",
    name="CMDB",
    status="planned",
    description=(
        "Configuration management database. PLANNED — NOT yet callable. "
        "Mutating operations may require approval when enabled."
    ),
    module=CapabilityModuleSpec(
        module_id="cmdb",
        status="planned",
        service_path="agent.modules.cmdb.service",
        operations=["extract_assets", "query_assets", "upsert_assets"],
        description="(planned) Asset management.",
    ),
    skills=[
        CapabilitySkillSpec(
            skill_id="cmdb",
            status="planned",
            related_tools=[
                "cmdb.extract_assets",
                "cmdb.query_assets",
                "cmdb.upsert_assets",
            ],
            intent_patterns=[
                "查资产",
                "资产管理",
                "cmdb",
                "asset lookup",
            ],
            required_inputs=[],
            prompt_summary=(
                "(planned) CMDB query and management. NOT yet callable. "
                "Do not fabricate asset records."
            ),
            preconditions=["Capability must be enabled (status=planned now)."],
            postconditions=["Never claim real CMDB data exists."],
            safety_rules=[
                "Do not claim CMDB data exists unless retrieved.",
                "Do not fabricate asset records.",
                "Mutating CMDB operations may require approval when enabled.",
            ],
        ),
    ],
    tools=[
        CapabilityToolRef(
            tool_id="cmdb.extract_assets",
            status="planned",
            callable_by_llm=False,
            risk_level="low",
            requires_approval=False,
            forbidden=False,
            handler_ref="",
            description="(planned) Extract assets from a source.",
        ),
        CapabilityToolRef(
            tool_id="cmdb.query_assets",
            status="planned",
            callable_by_llm=False,
            risk_level="low",
            requires_approval=False,
            forbidden=False,
            handler_ref="",
            description="(planned) Query assets.",
        ),
        CapabilityToolRef(
            tool_id="cmdb.upsert_assets",
            status="planned",
            callable_by_llm=False,
            risk_level="medium",
            requires_approval=True,
            forbidden=False,
            handler_ref="",
            description="(planned) Upsert asset records (approval required).",
        ),
    ],
    outputs=[
        CapabilityOutputSpec(
            output_id="asset_records",
            output_type="asset_records",
            description="(planned) Asset records.",
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
        requires_human_review=True,
        notes="Planned only. Mutating ops require approval when enabled.",
    ),
    dependencies=[],
    metadata={"version": "0.8.0-planned", "owners": ["agent_backend"]},
)
