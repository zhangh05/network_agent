# agent/modules/topology/capability.py
"""Capability manifest for Topology — planned."""

from agent.capabilities.schemas import (
    CapabilityManifest,
    CapabilityModuleSpec,
    CapabilityToolRef,
    CapabilityOutputSpec,
    CapabilitySafetySpec,
)


CAPABILITY_TOPOLOGY = CapabilityManifest(
    capability_id="topology",
    name="Topology",
    status="planned",
    description="网络拓扑发现与可视化（规划中）。",
    intent_patterns=["拓扑", "topology", "网络拓扑"],
    prompt_summary="网络拓扑自动发现与可视化（规划中）。",
    module=CapabilityModuleSpec(
        module_id="topology", status="planned",
        service_path="agent.modules.topology.service",
        operations=[],
        description="Topology service (planned).",
    ),
    tools=[],
    outputs=[],
    safety=CapabilitySafetySpec(
        real_device_access=False, allows_config_push=False,
        produces_deployable_config=False, may_fabricate_sources=False,
        requires_human_review=False, notes="Planned — not yet available.",
    ),
    dependencies=[],
    metadata={"version": "0.0.1-dev", "owners": ["agent_backend"]},
)
