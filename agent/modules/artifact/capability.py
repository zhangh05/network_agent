# agent/modules/artifact/capability.py
"""Capability manifest for artifact management (v0.9, enabled).

Single source of truth for the artifact capability. Four tools:
  - workspace.artifact.list   (LLM-callable; browse artifacts in workspace/session)
  - workspace.artifact.read   (LLM-callable; read content + metadata)
  - workspace.artifact.diff   (LLM-callable; text/structured diff between two artifacts)
  - workspace.artifact.export (LLM-callable; render as txt / md, no real device push)

Strict safety contract:
  - no real device access
  - no config.push
  - no authoritative deployable_config generation
  - no fabrication
"""

from agent.capabilities.schemas import (
    CapabilityManifest,
    CapabilityModuleSpec,
    CapabilitySkillSpec,
    CapabilityToolRef,
    CapabilityOutputSpec,
    CapabilitySafetySpec,
)


CAPABILITY_ARTIFACT = CapabilityManifest(
    capability_id="artifact",
    name="Artifact Management",
    status="enabled",
    description=(
        "List, read, diff, and export artifacts already produced by other "
        "capabilities (e.g. translated_config). Does NOT connect to real "
        "devices, does NOT push configuration, and does NOT generate "
        "authoritative deployable_config. Artifact content is read verbatim "
        "from the existing artifact store."
    ),
    module=CapabilityModuleSpec(
        module_id="artifact",
        status="enabled",
        service_path="agent.modules.artifact.service",
        operations=["list_artifacts_for_session", "read_artifact", "diff_artifacts", "export_artifact"],
        description=(
            "Reads existing artifacts via artifacts.store. Returns a sanitized "
            "list (no local paths), full content (with sensitivity gating), "
            "unified text diff, and txt / md export. No side effects on "
            "production infrastructure."
        ),
    ),
    skills=[
        CapabilitySkillSpec(
            skill_id="artifact_management",
            status="enabled",
            related_tools=[
                "workspace.artifact.list", "workspace.artifact.read",
                "workspace.artifact.diff", "workspace.artifact.export",
            ],
            intent_patterns=[
                "查看产物", "列出产物", "读取 artifact", "读取产物",
                "导出结果", "导出配置", "比较结果", "对比两个产物",
                "diff", "查看 artifact",
                "list artifacts", "read artifact", "export result",
                "compare results", "diff configs",
            ],
            required_inputs=[],
            prompt_summary=(
                "Use artifact_management when the user asks to list, read, "
                "diff, or export an artifact. Never claim an artifact exists "
                "without verifying via workspace.artifact.list. Never generate new "
                "config; only return what the artifact already contains."
            ),
            preconditions=["User must reference an artifact_id, session, or workspace."],
            postconditions=[
                "workspace.artifact.read is called, surface authoritative=false / "
                "deployable_config=false when present.",
                "Never claim the exported text is deployable_config.",
            ],
            safety_rules=[
                "Never fabricate artifact content.",
                "Never claim a real device was touched.",
                "translated_config artifacts are NOT deployable_config.",
                "workspace.artifact.export is a text rendering, not a push.",
            ],
        ),
    ],
    tools=[
        CapabilityToolRef(
            tool_id="workspace.artifact.list",
            status="enabled",
            callable_by_llm=True,
            risk_level="low",
            requires_approval=False,
            forbidden=False,
            handler_ref="agent.modules.artifact.tools:tool_handler_list",
            input_schema={
                "type": "object",
                "properties": {
                    "workspace_id": {"type": "string", "description": "Workspace id."},
                    "session_id": {"type": "string", "description": "Optional session id filter."},
                    "artifact_type": {"type": "string", "description": "Optional type filter (e.g. translated_config)."},
                    "limit": {"type": "integer", "description": "Maximum number of records to return."},
                },
                "required": ["workspace_id"],
            },
            description=(
                "List artifacts in a workspace, optionally filtered by session, "
                "type, or limit. Returns sanitized records (no local file paths)."
            ),
        ),
        CapabilityToolRef(
            tool_id="workspace.artifact.read",
            status="enabled",
            callable_by_llm=True,
            risk_level="low",
            requires_approval=False,
            forbidden=False,
            handler_ref="agent.modules.artifact.tools:tool_handler_read",
            input_schema={
                "type": "object",
                "properties": {
                    "workspace_id": {"type": "string", "description": "Workspace id."},
                    "artifact_id": {"type": "string", "description": "Artifact id (e.g. art_xxxx)."},
                    "allow_sensitive": {
                        "type": "boolean",
                        "description": "If true, allow content of sensitive artifacts.",
                    },
                },
                "required": ["workspace_id", "artifact_id"],
            },
            description=(
                "Read the content + metadata of an artifact. Returns "
                "ok=false when the artifact is missing or sensitivity gates "
                "deny access. translated_config artifacts are returned "
                "verbatim with authoritative=false / deployable_config=false."
            ),
        ),
        CapabilityToolRef(
            tool_id="workspace.artifact.diff",
            status="enabled",
            callable_by_llm=True,
            risk_level="low",
            requires_approval=False,
            forbidden=False,
            handler_ref="agent.modules.artifact.tools:tool_handler_diff",
            input_schema={
                "type": "object",
                "properties": {
                    "workspace_id": {"type": "string", "description": "Workspace id."},
                    "left_artifact_id": {"type": "string", "description": "Left artifact id."},
                    "right_artifact_id": {"type": "string", "description": "Right artifact id."},
                    "max_lines": {"type": "integer", "description": "Cap the unified diff to N lines (default 200)."},
                },
                "required": ["workspace_id", "left_artifact_id", "right_artifact_id"],
            },
            description=(
                "Compute a unified text diff between two artifacts in the same "
                "workspace. Returns ok=false when either artifact is missing."
            ),
        ),
        CapabilityToolRef(
            tool_id="workspace.artifact.export",
            status="enabled",
            callable_by_llm=True,
            risk_level="low",
            requires_approval=False,
            forbidden=False,
            handler_ref="agent.modules.artifact.tools:tool_handler_export",
            input_schema={
                "type": "object",
                "properties": {
                    "workspace_id": {"type": "string", "description": "Workspace id."},
                    "artifact_id": {"type": "string", "description": "Artifact id."},
                    "format": {
                        "type": "string",
                        "description": "Export format: 'txt' (raw content) or 'md' (rendered with metadata header).",
                        "enum": ["txt", "md"],
                    },
                },
                "required": ["workspace_id", "artifact_id", "format"],
            },
            description=(
                "Render an artifact as text (txt) or markdown (md). Does NOT "
                "push to a real device and does NOT generate a deployable "
                "config; it is purely a local text rendering."
            ),
        ),
    ],
    outputs=[
        CapabilityOutputSpec(
            output_id="artifact_list",
            output_type="artifact_list",
            description="Sanitized list of artifacts (no local paths).",
            artifact_type="",
            visible_to_user=True,
            sensitivity="internal",
            authoritative=False,
        ),
        CapabilityOutputSpec(
            output_id="artifact_content",
            output_type="artifact_content",
            description="Full content of an artifact (verbatim from store).",
            artifact_type="",
            visible_to_user=True,
            sensitivity="sensitive",
            authoritative=False,
        ),
        CapabilityOutputSpec(
            output_id="artifact_diff",
            output_type="artifact_diff",
            description="Unified text diff between two artifacts.",
            artifact_type="",
            visible_to_user=True,
            sensitivity="internal",
            authoritative=False,
        ),
        CapabilityOutputSpec(
            output_id="artifact_export",
            output_type="artifact_export",
            description="Local rendering of an artifact (txt / md).",
            artifact_type="",
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
        requires_human_review=False,
        notes=(
            "Strict read-only surface over the existing artifact store. "
            "translated_config artifacts stay authoritative=false / "
            "deployable_config=false. No side effects on production state."
        ),
    ),
    dependencies=[],
    metadata={"version": "0.9", "owners": ["agent_backend"]},
)
