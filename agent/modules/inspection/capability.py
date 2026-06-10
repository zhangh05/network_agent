# agent/modules/inspection/capability.py
"""Capability manifest for inspection (PLANNED — NOT callable)."""

from agent.capabilities.schemas import (
    CapabilityManifest,
    CapabilityModuleSpec,
    CapabilitySkillSpec,
    CapabilityToolRef,
    CapabilityOutputSpec,
    CapabilitySafetySpec,
)


CAPABILITY_INSPECTION = CapabilityManifest(
    capability_id="inspection",
    name="Inspection",
    status="planned",
    description=(
        "Network device inspection and health-check analysis. PLANNED — "
        "NOT yet callable. Only analyzes user-provided show/display "
        "outputs when enabled. No real device login."
    ),
    module=CapabilityModuleSpec(
        module_id="inspection",
        status="planned",
        service_path="agent.modules.inspection.service",
        operations=["analyze_outputs", "generate_report"],
        description="(planned) Inspection report generation.",
    ),
    skills=[
        CapabilitySkillSpec(
            skill_id="inspection",
            status="planned",
            related_tools=["inspection.analyze_outputs", "inspection.generate_report"],
            intent_patterns=[
                "巡检",
                "健康检查",
                "设备巡检",
                "inspection",
                "health check",
            ],
            required_inputs=[],
            prompt_summary=(
                "(planned) Inspection analysis. NOT yet callable. Do not "
                "claim real device login or fabricate findings."
            ),
            preconditions=["Capability must be enabled (status=planned now)."],
            postconditions=["Never claim a real device was inspected."],
            safety_rules=[
                "Only analyze user-provided show/display outputs when enabled.",
                "Do not claim real device login.",
                "Do not fabricate inspection findings.",
            ],
        ),
    ],
    tools=[
        CapabilityToolRef(
            tool_id="inspection.analyze_outputs",
            status="planned",
            callable_by_llm=False,
            risk_level="low",
            requires_approval=False,
            forbidden=False,
            handler_ref="",
            description="(planned) Analyze user-provided show/display outputs.",
        ),
        CapabilityToolRef(
            tool_id="inspection.generate_report",
            status="planned",
            callable_by_llm=False,
            risk_level="low",
            requires_approval=False,
            forbidden=False,
            handler_ref="",
            description="(planned) Generate inspection report.",
        ),
    ],
    outputs=[
        CapabilityOutputSpec(
            output_id="inspection_report",
            output_type="inspection_report",
            description="(planned) Inspection report.",
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
        notes="Planned only. No real device login. Mutating ops require approval.",
    ),
    dependencies=[],
    metadata={"version": "0.8.0-planned", "owners": ["agent_backend"]},
)
