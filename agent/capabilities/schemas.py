# agent/capabilities/schemas.py
"""CapabilityLayer v0.8 — capability manifest schemas.

This module defines the dataclass contracts for a Capability:

    CapabilityManifest
        capability_id, name, status, description
        module: CapabilityModuleSpec
        tools:  list[CapabilityToolRef]
        outputs: list[CapabilityOutputSpec]
        safety: CapabilitySafetySpec
        intent_patterns: list[str]
        prompt_summary: str
        dependencies: list[str]
        metadata: dict

Status values: enabled | planned | disabled
- enabled:     visible to LLM (after ToolRouter / ToolRegistry contract)
- planned:     NOT injected, NOT callable, NOT fabricated
- disabled:    explicitly off

The manifest is the single source of truth for runtime visibility.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any


VALID_CAPABILITY_STATUSES = {"enabled", "planned", "disabled"}
VALID_TOOL_STATUSES = {"enabled", "planned", "disabled"}
VALID_RISK_LEVELS = {"low", "medium", "high", "forbidden"}


@dataclass
class CapabilityStatus:
    """Status descriptor for any sub-component of a capability."""

    value: str = "disabled"  # enabled | planned | disabled

    def __post_init__(self):
        if self.value not in VALID_CAPABILITY_STATUSES:
            raise ValueError(
                f"Invalid CapabilityStatus: {self.value!r}; "
                f"must be one of {sorted(VALID_CAPABILITY_STATUSES)}"
            )

    @property
    def is_enabled(self) -> bool:
        return self.value == "enabled"

    @property
    def is_planned(self) -> bool:
        return self.value == "planned"

    def as_dict(self) -> dict:
        return {"value": self.value}


@dataclass
class CapabilityModuleSpec:
    """Module layer of a capability.

    A Module is the business-implementation layer. It does not know about
    LLM / Skill / ToolRouter.
    """

    module_id: str = ""
    status: str = "disabled"            # enabled | planned | disabled
    service_path: str = ""              # e.g. "agent.modules.config_translation.service"
    operations: List[str] = field(default_factory=list)  # entry operation names
    description: str = ""

    def __post_init__(self):
        if self.status not in VALID_CAPABILITY_STATUSES:
            raise ValueError(
                f"Invalid module status: {self.status!r}; "
                f"must be one of {sorted(VALID_CAPABILITY_STATUSES)}"
            )

    def as_dict(self) -> dict:
        return {
            "module_id": self.module_id,
            "status": self.status,
            "service_path": self.service_path,
            "operations": list(self.operations),
            "description": self.description,
        }


@dataclass
class CapabilityToolRef:
    """Tool layer of a capability.

    A Tool is the LLM-callable entry. It performs lightweight argument
    validation and dispatches to the underlying Module. Risk/approval
    metadata is recorded here, NOT in the Module.
    """

    tool_id: str = ""
    status: str = "disabled"
    callable_by_llm: bool = False
    risk_level: str = "low"            # low | medium | high | forbidden
    requires_approval: bool = False
    forbidden: bool = False
    handler_ref: str = ""              # dotted path; resolved lazily
    input_schema: Dict[str, Any] = field(default_factory=dict)
    description: str = ""

    def __post_init__(self):
        if self.status not in VALID_TOOL_STATUSES:
            raise ValueError(
                f"Invalid tool status: {self.status!r}; "
                f"must be one of {sorted(VALID_TOOL_STATUSES)}"
            )
        if self.risk_level not in VALID_RISK_LEVELS:
            raise ValueError(
                f"Invalid risk_level: {self.risk_level!r}; "
                f"must be one of {sorted(VALID_RISK_LEVELS)}"
            )
        if self.status == "enabled":
            if not self.handler_ref:
                raise ValueError(
                    f"Enabled tool {self.tool_id!r} must declare handler_ref"
                )
        if self.forbidden and self.callable_by_llm:
            raise ValueError(
                f"Tool {self.tool_id!r} is forbidden; callable_by_llm must be False"
            )

    def as_dict(self) -> dict:
        return {
            "tool_id": self.tool_id,
            "status": self.status,
            "callable_by_llm": self.callable_by_llm,
            "risk_level": self.risk_level,
            "requires_approval": self.requires_approval,
            "forbidden": self.forbidden,
            "handler_ref": self.handler_ref,
            "input_schema": dict(self.input_schema),
            "description": self.description,
        }


@dataclass
class CapabilityOutputSpec:
    """Output Contract: what the capability produces.

    Used by RuntimeSnapshot, the LLM, and the UI to describe the artifact
    surface of the capability.
    """

    output_id: str = ""
    output_type: str = ""              # e.g. "translated_config", "source_summary"
    description: str = ""
    artifact_type: str = ""            # e.g. "translated_config"
    visible_to_user: bool = True
    sensitivity: str = "internal"      # public | internal | sensitive | secret
    authoritative: bool = False        # True only when the capability
                                       # is the authoritative producer
    metadata: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "output_id": self.output_id,
            "output_type": self.output_type,
            "description": self.description,
            "artifact_type": self.artifact_type,
            "visible_to_user": self.visible_to_user,
            "sensitivity": self.sensitivity,
            "authoritative": self.authoritative,
            "metadata": dict(self.metadata),
        }


@dataclass
class CapabilitySafetySpec:
    """Safety Contract: every capability MUST declare this.

    Default values are conservative: no real device access, no config
    push, no authoritative deployable_config, no fabrication, no human
    review required. Capabilities that violate these defaults MUST set
    the corresponding field to True AND record a `notes` justification.
    """

    real_device_access: bool = False
    allows_config_push: bool = False
    produces_deployable_config: bool = False
    may_fabricate_sources: bool = False
    requires_human_review: bool = False
    notes: str = ""

    def as_dict(self) -> dict:
        return {
            "real_device_access": self.real_device_access,
            "allows_config_push": self.allows_config_push,
            "produces_deployable_config": self.produces_deployable_config,
            "may_fabricate_sources": self.may_fabricate_sources,
            "requires_human_review": self.requires_human_review,
            "notes": self.notes,
        }


@dataclass
class CapabilityManifest:
    """Canonical, truth-source definition of a business capability.

    A Capability is the bundle of:
        Module  (business implementation)
      + Tool(s) (LLM-callable entry; risk/approval metadata)
      + Skill(s) (LLM guidance: when to use, what to expect)
      + Output Contract (artifact / summary / source shape)
      + Safety Contract (real-device, config-push, fabrication rules)

    RuntimeSnapshot / ModuleRegistry / SkillRegistry / ToolRegistry all
    derive from this manifest.
    """

    capability_id: str = ""
    name: str = ""
    status: str = "disabled"            # enabled | planned | disabled
    description: str = ""
    module: CapabilityModuleSpec = field(default_factory=CapabilityModuleSpec)
    intent_patterns: List[str] = field(default_factory=list)
    prompt_summary: str = ""
    tools: List[CapabilityToolRef] = field(default_factory=list)
    outputs: List[CapabilityOutputSpec] = field(default_factory=list)
    safety: CapabilitySafetySpec = field(default_factory=CapabilitySafetySpec)
    dependencies: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.status not in VALID_CAPABILITY_STATUSES:
            raise ValueError(
                f"Invalid capability status: {self.status!r}; "
                f"must be one of {sorted(VALID_CAPABILITY_STATUSES)}"
            )
        if self.status == "enabled":
            if not self.module.module_id:
                raise ValueError(
                    f"Enabled capability {self.capability_id!r} must declare a module"
                )
            if not self.tools:
                raise ValueError(
                    f"Enabled capability {self.capability_id!r} must declare at least one tool"
                )
        # Cross-check: planned capabilities must not expose any enabled tools.
        if self.status == "planned":
            for t in self.tools:
                if t.status == "enabled":
                    raise ValueError(
                        f"Planned capability {self.capability_id!r} cannot declare "
                        f"enabled tool {t.tool_id!r}"
                    )
                if t.callable_by_llm:
                    raise ValueError(
                        f"Planned capability {self.capability_id!r} tool {t.tool_id!r} "
                        f"must have callable_by_llm=False"
                    )

    def as_dict(self) -> dict:
        return {
            "capability_id": self.capability_id,
            "name": self.name,
            "status": self.status,
            "description": self.description,
            "module": self.module.as_dict(),
            "intent_patterns": list(self.intent_patterns),
            "prompt_summary": self.prompt_summary,
            "tools": [t.as_dict() for t in self.tools],
            "outputs": [o.as_dict() for o in self.outputs],
            "safety": self.safety.as_dict(),
            "dependencies": list(self.dependencies),
            "metadata": dict(self.metadata),
        }
