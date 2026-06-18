# agent/modules/topology/capability.py
"""Capability manifest for topology (PLANNED — NOT callable).

This manifest is the truth-source for the planned topology capability.
It is intentionally expressed as `status="planned"` with all tool refs
set to `callable_by_llm=False`. The CapabilityRegistry MUST NOT inject
these tools into the model-visible whitelist.
"""

from agent.capabilities.schemas import (
    CapabilityManifest,
    CapabilityModuleSpec,
    CapabilitySkillSpec,
    CapabilityToolRef,
    CapabilityOutputSpec,
    CapabilitySafetySpec,
)


CAPABILITY_TOPOLOGY = CapabilityManifest(
    capability_id="topology",
    name="Topology",
    status="planned",
    description=(
        "Network topology extraction and rendering. PLANNED — NOT yet "
        "callable. Do not claim topology can be generated now."
    ),
    module=CapabilityModuleSpec(
        module_id="topology",
        status="planned",
        service_path="agent.modules.topology.service",
        operations=["extract_topology", "render_topology"],
        description="(planned) Network topology analysis.",
    ),
    skills=[
        CapabilitySkillSpec(
            skill_id="topology",
            status="planned",
            related_tools=["topology.extract", "topology.render"],
            intent_patterns=[
                "画拓扑",
                "生成网络拓扑",
                "画一下拓扑图",
                "topology",
                "render topology",
            ],
            required_inputs=[],
            prompt_summary=(
                "(planned) Topology extraction and rendering. NOT yet "
                "callable; do not fabricate devices, interfaces, or links."
            ),
            preconditions=["Capability must be enabled (status=planned now)."],
            postconditions=["Never claim a real topology was generated."],
            safety_rules=[
                "Do not claim topology can be generated now.",
                "Do not fabricate devices, interfaces, or links.",
            ],
        ),
    ],
    tools=[
        CapabilityToolRef(
            tool_id="topology.extract",
            status="planned",
            callable_by_llm=False,
            risk_level="low",
            requires_approval=False,
            forbidden=False,
            handler_ref="",
            description="(planned) Extract topology from a source.",
        ),
        CapabilityToolRef(
            tool_id="topology.render",
            status="planned",
            callable_by_llm=False,
            risk_level="low",
            requires_approval=False,
            forbidden=False,
            handler_ref="",
            description="(planned) Render extracted topology.",
        ),
    ],
    outputs=[
        CapabilityOutputSpec(
            output_id="topology_graph",
            output_type="topology_graph",
            description="(planned) Topology graph output.",
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
        notes="Planned only. No real device probing, no link fabrication.",
    ),
    dependencies=[],
    metadata={"version": "0.8.0-planned", "owners": ["agent_backend"]},
)
