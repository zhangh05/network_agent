# agent/modules/inspection/capability.py
"""Capability manifest for Inspection — planned."""

from agent.capabilities.schemas import (
    CapabilityManifest,
    CapabilityModuleSpec,
    CapabilityToolRef,
    CapabilityOutputSpec,
    CapabilitySafetySpec,
)


CAPABILITY_INSPECTION = CapabilityManifest(
    capability_id="inspection",
    name="Inspection",
    status="planned",
    description="设备巡检自动化（规划中）。",
    intent_patterns=["巡检", "inspection", "健康检查", "设备状态"],
    prompt_summary="网络设备自动化巡检（规划中）。",
    module=CapabilityModuleSpec(
        module_id="inspection", status="planned",
        service_path="agent.modules.inspection.service",
        operations=[],
        description="Inspection service (planned).",
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
