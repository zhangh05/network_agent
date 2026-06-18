# registry/validator.py
"""Registry validator — validate module/skill/capability contracts."""

import os
from pathlib import Path
from registry.schemas import (
    ModuleSpec, SkillSpec, CapabilitySpec, ValidationResult,
    RegistryValidationReport, VALID_STATUSES, VALID_MATURITIES, VALID_SKILL_TYPES,
)
from registry.loader import load_module_registry, load_skill_registry, load_capabilities

ROOT = Path(__file__).resolve().parent.parent


def validate_module(spec: ModuleSpec, module_path: str = "") -> ValidationResult:
    v = ValidationResult(source=f"module:{spec.module_name}")

    # Required fields
    if not spec.module_name:
        v.add_error("module_name is empty")
    if spec.status not in VALID_STATUSES:
        v.add_error(f"invalid status: {spec.status}")
    if spec.maturity not in VALID_MATURITIES:
        v.add_warning(f"unknown maturity: {spec.maturity}")

    # Module path must exist
    mp = ROOT / spec.module_path if spec.module_path else None
    if spec.is_enabled() and (not mp or not mp.is_dir()):
        v.add_error(f"module_path not found: {spec.module_path}")

    # Enabled module must have primary endpoint
    if spec.is_enabled() and not spec.primary_endpoint:
        v.add_error("enabled module requires primary_endpoint")

    # Deployable output requires field
    if spec.can_generate_deployable and not spec.deployable_output_field:
        v.add_error("can_generate_deployable=true requires deployable_output_field")
    if spec.can_generate_deployable and not spec.requires_manual_review:
        v.add_warning("deployable module should require manual_review")

    # No LLM contract
    if spec.no_module_private_llm and spec.requires_llm:
        v.add_error("no_module_private_llm conflicts with requires_llm=true")

    # Check module doesn't import agent.llm
    if spec.no_module_private_llm and spec.is_enabled():
        mp = ROOT / spec.module_path
        for py_file in mp.rglob("*.py"):
            content = py_file.read_text()
            if "agent.llm" in content or "from agent.llm" in content:
                v.add_error(f"module imports agent.llm: {py_file}")

    # No retired frontend
    if spec.no_retired_frontend and spec.is_enabled():
        mp = ROOT / spec.module_path
        for retired_dir in ["frontend", "static", "templates", "web"]:
            if (mp / retired_dir).is_dir():
                v.add_error(f"module has retired frontend dir: {mp/retired_dir}")

    # No external repo
    if spec.no_external_repo_dependency:
        mp = ROOT / spec.module_path
        for py_file in mp.rglob("*.py"):
            content = py_file.read_text()
            if "network.translator" in content and "network-translator" in content:
                v.add_error(f"module references external network-translator: {py_file}")

    return v


def validate_skill(spec: SkillSpec) -> ValidationResult:
    v = ValidationResult(source=f"skill:{spec.skill_name}")

    if not spec.skill_name:
        v.add_error("skill_name is empty")
    if spec.status not in VALID_STATUSES:
        v.add_error(f"invalid status: {spec.status}")
    if spec.skill_type not in VALID_SKILL_TYPES:
        v.add_warning(f"unknown skill_type: {spec.skill_type}")

    # Module reference
    if spec.module:
        from registry.loader import get_module
        mod = get_module(spec.module)
        if not mod:
            v.add_error(f"referenced module not found: {spec.module}")
        elif spec.is_enabled() and not mod.is_enabled():
            v.add_error(f"enabled skill '{spec.skill_name}' references planned module '{spec.module}'")

    # Adapter path
    adapter = ROOT / spec.adapter_path if spec.adapter_path else None
    if spec.is_enabled() and spec.adapter_required and spec.requires_adapter:
        if not adapter or not adapter.is_file():
            v.add_error(f"adapter not found: {spec.adapter_path}")
        else:
            content = adapter.read_text()
            if "agent.llm" in content:
                v.add_error(f"adapter imports agent.llm: {spec.adapter_path}")
            if "requests." in content and "localhost" in content:
                v.add_warning(f"adapter may call localhost HTTP: {spec.adapter_path}")
            if "/api/translate" in content:
                v.add_error(f"adapter references /api/translate: {spec.adapter_path}")

    # Red lines check
    required_red_lines = {"do_not_call_llm", "do_not_hide_manual_review"}
    for rl in required_red_lines:
        if rl not in spec.red_lines:
            v.add_warning(f"missing recommended red_line: {rl}")

    return v


def validate_capability(spec: CapabilitySpec) -> ValidationResult:
    v = ValidationResult(source=f"capability:{spec.capability_id}")

    if not spec.capability_id:
        v.add_error("capability_id is empty")

    # References must exist
    from registry.loader import get_module, get_skill
    mod = get_module(spec.module)
    skill = get_skill(spec.skill)
    if not mod:
        v.add_error(f"module not found: {spec.module}")
    if not skill:
        v.add_error(f"skill not found: {spec.skill}")

    # Enabled capability needs enabled module + skill
    if spec.is_enabled():
        if mod and not mod.is_enabled():
            v.add_error(f"enabled capability '{spec.capability_id}' requires enabled module '{spec.module}'")
        if skill and not skill.is_enabled():
            v.add_error(f"enabled capability '{spec.capability_id}' requires enabled skill '{spec.skill}'")

    # Deployable requires verification
    if spec.can_generate_deployable and not spec.requires_verification:
        v.add_error("can_generate_deployable requires requires_verification=true")

    return v


def validate_all(modules: list = None, skills: list = None, capabilities: list = None) -> RegistryValidationReport:
    if modules is None:
        modules = load_module_registry()
    if skills is None:
        skills = load_skill_registry()
    if capabilities is None:
        capabilities = load_capabilities()

    report = RegistryValidationReport()

    # Validate modules
    for m in modules:
        v = validate_module(m, m.module_path)
        report.module_results[m.module_name] = v

    # Validate skills
    for s in skills:
        v = validate_skill(s)
        report.skill_results[s.skill_name] = v

    # Validate capabilities
    cap_ids = set()
    for c in capabilities:
        if c.capability_id in cap_ids:
            report.global_errors.append(f"duplicate capability_id: {c.capability_id}")
        cap_ids.add(c.capability_id)
        v = validate_capability(c)
        report.capability_results[c.capability_id] = v

    # Global checks
    return report


def generate_validation_report() -> dict:
    """Generate a JSON-serializable validation report."""
    report = validate_all()
    errors = []
    warnings = []

    for name, v in report.module_results.items():
        for e in v.errors:
            errors.append(f"[module:{name}] {e}")
        for w in v.warnings:
            warnings.append(f"[module:{name}] {w}")

    for name, v in report.skill_results.items():
        for e in v.errors:
            errors.append(f"[skill:{name}] {e}")
        for w in v.warnings:
            warnings.append(f"[skill:{name}] {w}")

    for name, v in report.capability_results.items():
        for e in v.errors:
            errors.append(f"[capability:{name}] {e}")
        for w in v.warnings:
            warnings.append(f"[capability:{name}] {w}")

    errors.extend(report.global_errors)
    warnings.extend(report.global_warnings)

    return {
        "valid": report.ok,
        "errors": errors,
        "warnings": warnings,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "module_results": {k: {"ok": v.ok, "errors": v.errors, "warnings": v.warnings}
                          for k, v in report.module_results.items()},
        "skill_results": {k: {"ok": v.ok, "errors": v.errors, "warnings": v.warnings}
                         for k, v in report.skill_results.items()},
    }
