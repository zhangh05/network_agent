# agent/modules/review/capability.py
"""Capability manifest for Manual Review."""

from agent.capabilities.schemas import (
    CapabilityManifest,
    CapabilityModuleSpec,
    CapabilityToolRef,
    CapabilityOutputSpec,
    CapabilitySafetySpec,
)


CAPABILITY_REVIEW = CapabilityManifest(
    capability_id="review_flow",
    name="Manual Review",
    status="enabled",
    description="人工审核流程。列出待审核项、更新审核状态。",
    intent_patterns=["审核", "review", "待审核", "审批", "review items"],
    prompt_summary="人工审核管理。列出待审核项，标记通过或拒绝。",
    module=CapabilityModuleSpec(
        module_id="review", status="enabled",
        service_path="agent.modules.review.service",
        operations=["list", "update"],
        description="Manual review flow management.",
    ),
    tools=[
        CapabilityToolRef(
            tool_id="system.system.review.item.list",
            status="enabled", callable_by_llm=True, risk_level="low",
            requires_approval=False, forbidden=False,
            handler_ref="tool_runtime.canonical_registry:_handler_review_list",
            description="列出待审核项。",
        ),
        CapabilityToolRef(
            tool_id="system.system.review.item.update",
            status="enabled", callable_by_llm=True, risk_level="medium",
            requires_approval=True, forbidden=False,
            handler_ref="tool_runtime.canonical_registry:_handler_review_update",
            description="更新审核状态。需用户确认。",
        ),
    ],
    outputs=[CapabilityOutputSpec(
        output_id="review_result",
        output_type="review_result",
        description="审核结果。",
        artifact_type="review", visible_to_user=True,
        sensitivity="internal", authoritative=True,
    )],
    safety=CapabilitySafetySpec(
        real_device_access=False, allows_config_push=False,
        produces_deployable_config=False, may_fabricate_sources=False,
        requires_human_review=True, notes="审核操作需人工确认。",
    ),
    dependencies=[],
    metadata={"version": "1.0.0", "owners": ["agent_backend"]},
)
