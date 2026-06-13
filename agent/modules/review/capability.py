# agent/modules/review/capability.py
"""Capability manifest for review flow (v0.9, enabled).

Two tools:
  - review.list_items   (LLM-callable; return manual_review_items for an
                         artifact, with current status / user_note)
  - review.update_item  (LLM-callable; update status (pending /
                         accepted / ignored / modified) and user_note
                         for one item)

Strict safety:
  - never modifies the original translated_config content
  - never produces a deployable_config
  - never touches a real device
"""

from agent.capabilities.schemas import (
    CapabilityManifest,
    CapabilityModuleSpec,
    CapabilitySkillSpec,
    CapabilityToolRef,
    CapabilityOutputSpec,
    CapabilitySafetySpec,
)


CAPABILITY_REVIEW = CapabilityManifest(
    capability_id="review",
    name="Manual Review",
    status="enabled",
    description=(
        "Inspect and update manual_review_items attached to an artifact. "
        "Supports listing items and updating each item's status "
        "(pending / accepted / ignored / modified) plus a user_note. "
        "NEVER modifies the original artifact content. NEVER generates a "
        "deployable_config. NEVER touches a real device."
    ),
    module=CapabilityModuleSpec(
        module_id="review",
        status="enabled",
        service_path="agent.modules.review.service",
        operations=["list_review_items", "update_review_item"],
        description=(
            "Read / update a sidecar JSON file at "
            "{ws_root}/{workspace}/reviews/{artifact_id}.json. Sidecar "
            "stores per-item {status, user_note, updated_at}. Original "
            "artifact metadata is never written to."
        ),
    ),
    skills=[
        CapabilitySkillSpec(
            skill_id="review_flow",
            status="enabled",
            related_tools=["review.list_items", "review.update_item"],
            intent_patterns=[
                "人工复核", "人工审核", "复核项", "复核",
                "确认", "忽略", "修改建议", "review", "review item",
                "manual review", "accept", "ignore", "modify suggestion",
            ],
            required_inputs=[],
            prompt_summary=(
                "Use review_flow when the user asks to inspect or update "
                "manual_review_items. update_item only changes the "
                "sidecar {status, user_note, updated_at}; the original "
                "artifact and its translated_config remain unchanged."
            ),
            preconditions=["User must reference an artifact_id and item_id."],
            postconditions=[
                "Always surface that the original translated_config is NOT "
                "modified and is NOT a deployable_config.",
            ],
            safety_rules=[
                "Never modify the original translated_config content.",
                "Never produce a deployable_config.",
                "Never claim the review status makes the config deployable.",
                "All review changes go into a per-artifact sidecar JSON.",
            ],
        ),
    ],
    tools=[
        CapabilityToolRef(
            tool_id="review.list_items",
            status="enabled",
            callable_by_llm=True,
            risk_level="low",
            requires_approval=False,
            forbidden=False,
            handler_ref="agent.modules.review.tools:tool_handler_list",
            input_schema={
                "type": "object",
                "properties": {
                    "workspace_id": {"type": "string", "description": "Workspace id."},
                    "artifact_id": {"type": "string", "description": "Artifact id."},
                },
                "required": ["workspace_id", "artifact_id"],
            },
            description=(
                "List manual_review_items for an artifact with their current "
                "status (pending / accepted / ignored / modified) and "
                "user_note. Items come from the artifact's metadata + the "
                "review sidecar."
            ),
        ),
        CapabilityToolRef(
            tool_id="review.update_item",
            status="enabled",
            callable_by_llm=True,
            risk_level="low",
            requires_approval=False,
            forbidden=False,
            handler_ref="agent.modules.review.tools:tool_handler_update",
            input_schema={
                "type": "object",
                "properties": {
                    "workspace_id": {"type": "string", "description": "Workspace id."},
                    "artifact_id": {"type": "string", "description": "Artifact id."},
                    "item_id": {"type": "string", "description": "Review item id from list_items."},
                    "status": {
                        "type": "string",
                        "enum": ["pending", "accepted", "ignored", "modified"],
                    },
                    "user_note": {"type": "string", "description": "Optional note explaining the decision."},
                },
                "required": ["workspace_id", "artifact_id", "item_id", "status"],
            },
            description=(
                "Update one manual_review_item's status and user_note in the "
                "sidecar JSON. Does NOT modify the original artifact content "
                "and does NOT produce a deployable_config."
            ),
        ),
    ],
    outputs=[
        CapabilityOutputSpec(
            output_id="review_items",
            output_type="manual_review_items",
            description="Manual review items with current status / user_note.",
            artifact_type="",
            visible_to_user=True,
            sensitivity="internal",
            authoritative=False,
        ),
        CapabilityOutputSpec(
            output_id="review_item_update",
            output_type="review_item_update",
            description="Result of updating one review item.",
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
        notes=(
            "Review sidecar is per-artifact; original artifact is "
            "untouched. The capability is exactly the human-review surface; "
            "no auto-accept / no auto-deploy."
        ),
    ),
    dependencies=["artifact"],
    metadata={"version": "0.9", "owners": ["agent_backend"]},
)
