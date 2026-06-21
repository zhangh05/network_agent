# registry/schemas.py
"""ModuleSpec, SkillSpec, CapabilitySpec — canonical registry schemas."""

from dataclasses import dataclass, field
from typing import Any, Optional

# Valid enums
VALID_STATUSES = {"enabled", "planned", "disabled"}
VALID_MATURITIES = {"experimental", "embedded_mvp", "beta_ready", "production_ready", "planned"}
# Removed tool-runtime naming is intentionally not accepted here.
# It must NOT be used for future Tool Runtime design, which will use independent
# ToolSpec / ToolRegistry / ToolInvocation / ToolResult.
# New skills must use python_adapter, prompt_skill, or workflow_skill.
VALID_SKILL_TYPES = {"python_adapter", "prompt_skill", "workflow_skill", "external_tool"}


@dataclass
class ModuleSpec:
    module_name: str = ""
    display_name: str = ""
    description: str = ""
    category: str = ""
    status: str = "planned"
    maturity: str = "planned"
    module_path: str = ""

    # Backend
    api_base: str = ""
    primary_endpoint: str = ""
    health_endpoint: str = ""

    # UI
    has_ui: bool = False
    ui_route: str = ""
    ui_owned_by: str = "network_agent_unified_ui"
    has_own_retired_frontend: bool = False

    # Runtime
    requires_llm: bool = False
    llm_allowed: bool = False
    deterministic: bool = True
    can_generate_deployable: bool = False
    deployable_output_field: str = ""

    # Risk
    risk_level: str = "low"
    can_affect_network: bool = False
    requires_manual_review: bool = False
    high_risk_output_possible: bool = False

    # I/O
    inputs: list = field(default_factory=list)
    outputs: list = field(default_factory=list)

    # Artifacts
    artifact_input_policy: str = "none"
    artifact_output_policy: str = "none"
    artifact_report_policy: str = "none"

    # Memory
    memory_write_run_summary: bool = False
    memory_allowed_types: list = field(default_factory=list)

    # Trace
    trace_enabled: bool = True
    trace_record_counts: bool = True
    trace_policy: str = "sanitized_metadata_only"

    # Security
    no_external_repo_dependency: bool = True
    no_module_private_llm: bool = True
    no_retired_frontend: bool = True
    no_retired_graphagent: bool = True
    no_api_key_storage: bool = True

    # Tests
    harness_tags: list = field(default_factory=list)
    required_contract_tests: list = field(default_factory=list)

    def is_enabled(self) -> bool: return self.status == "enabled"
    def is_planned(self) -> bool: return self.status == "planned"

    def as_dict(self) -> dict:
        return {
            "module_name": self.module_name, "display_name": self.display_name,
            "description": self.description, "category": self.category,
            "status": self.status, "maturity": self.maturity,
            "module_path": self.module_path,
            "api_base": self.api_base, "primary_endpoint": self.primary_endpoint,
            "has_ui": self.has_ui, "ui_route": self.ui_route,
            "requires_llm": self.requires_llm, "llm_allowed": self.llm_allowed,
            "can_generate_deployable": self.can_generate_deployable,
            "risk_level": self.risk_level, "requires_manual_review": self.requires_manual_review,
            "enabled": self.is_enabled(), "planned": self.is_planned(),
        }


@dataclass
class SkillSpec:
    skill_name: str = ""
    display_name: str = ""
    description: str = ""
    category: str = ""
    status: str = "planned"
    skill_type: str = "python_adapter"
    module: str = ""
    module_api: str = ""
    adapter_path: str = ""
    entrypoint_type: str = "python"
    entrypoint_function: str = ""
    capabilities: list = field(default_factory=list)
    calls_module: bool = True
    calls_llm: bool = False
    calls_http_self: bool = False
    direct_module_import_allowed: bool = True
    adapter_required: bool = True
    red_lines: list = field(default_factory=list)
    requires_adapter: bool = True
    trace_record_skill_call: bool = True
    trace_record_module_call: bool = True
    memory_write_run_summary: bool = True
    test_contracts: list = field(default_factory=list)
    # ── v0.3: generic artifact auto-save and compose config ──
    artifact: dict = field(default_factory=dict)
    compose: dict = field(default_factory=dict)

    def is_enabled(self) -> bool: return self.status == "enabled"
    def is_planned(self) -> bool: return self.status == "planned"

    def as_dict(self) -> dict:
        return {
            "skill_name": self.skill_name, "display_name": self.display_name,
            "description": self.description, "status": self.status,
            "skill_type": self.skill_type, "module": self.module,
            "capabilities": self.capabilities, "calls_llm": self.calls_llm,
            "red_lines": self.red_lines,
            "enabled": self.is_enabled(), "planned": self.is_planned(),
        }


@dataclass
class CapabilitySpec:
    capability_id: str = ""
    intent: str = ""
    module: str = ""
    skill: str = ""
    status: str = "planned"
    description: str = ""
    category: str = ""
    risk_level: str = "low"
    can_generate_deployable: bool = False
    requires_verification: bool = False
    requires_manual_review_if_any: bool = False
    llm_allowed: bool = False
    artifact_full_input_allowed: bool = False
    artifact_sensitivity: str = "internal"
    ui_module_route: str = ""
    ui_action_label: str = ""
    required_module: str = ""
    required_skill: str = ""
    input_schema: dict = field(default_factory=dict)
    output_schema: dict = field(default_factory=dict)
    policies: dict = field(default_factory=dict)

    def is_enabled(self) -> bool: return self.status == "enabled"

    def as_dict(self) -> dict:
        return {
            "capability_id": self.capability_id, "intent": self.intent,
            "module": self.module, "skill": self.skill,
            "status": self.status, "description": self.description,
            "category": self.category, "risk_level": self.risk_level,
            "can_generate_deployable": self.can_generate_deployable,
            "requires_verification": self.requires_verification,
            "enabled": self.is_enabled(),
        }


@dataclass
class ValidationResult:
    ok: bool = True
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    source: str = ""

    def add_error(self, msg: str):
        self.errors.append(msg)
        self.ok = False

    def add_warning(self, msg: str):
        self.warnings.append(msg)


@dataclass
class RegistryValidationReport:
    module_results: dict = field(default_factory=dict)
    skill_results: dict = field(default_factory=dict)
    capability_results: dict = field(default_factory=dict)
    global_errors: list = field(default_factory=list)
    global_warnings: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        for r in self.module_results.values():
            if not r.ok: return False
        for r in self.skill_results.values():
            if not r.ok: return False
        for r in self.capability_results.values():
            if not r.ok: return False
        return len(self.global_errors) == 0
