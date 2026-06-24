# agent/modules/artifact/capability.py
"""Capability manifest for Artifact Management."""

from agent.capabilities.schemas import (
    CapabilityManifest,
    CapabilityModuleSpec,
    CapabilityToolRef,
    CapabilityOutputSpec,
    CapabilitySafetySpec,
)


CAPABILITY_ARTIFACT = CapabilityManifest(
    capability_id="artifact_management",
    name="Artifact Management",
    status="enabled",
    description="Artifact 文件管理与预览。支持列出、读取 workspace 中的产出文件。",
    intent_patterns=["artifact", "产出文件", "报告文件", "生成的文件"],
    prompt_summary="浏览和读取 workspace 中已生成的 artifact 文件。",
    module=CapabilityModuleSpec(
        module_id="artifact", status="enabled",
        service_path="agent.modules.artifact.service",
        operations=["list", "read"],
        description="Artifact file listing and reading.",
    ),
    tools=[
        CapabilityToolRef(
            tool_id="workspace.artifact.save",
            status="enabled", callable_by_llm=True, risk_level="medium",
            requires_approval=False, forbidden=False,
            handler_ref="tool_runtime.canonical_registry:_handler_artifact_save",
            description="将分析结果/报告保存为 workspace artifact。",
        ),
    ],
    outputs=[CapabilityOutputSpec(
        output_id="artifact_info",
        output_type="artifact_info",
        description="Artifact 列表或内容。",
        artifact_type="artifact", visible_to_user=True,
        sensitivity="internal", authoritative=True,
    )],
    safety=CapabilitySafetySpec(
        real_device_access=False, allows_config_push=False,
        produces_deployable_config=False, may_fabricate_sources=False,
        requires_human_review=False, notes="只读操作。",
    ),
    dependencies=[],
    metadata={"version": "1.0.0", "owners": ["agent_backend"]},
)
