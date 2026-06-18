# registry/__init__.py
"""Registry — Module / Skill / Capability discovery and validation."""

from registry.loader import (
    load_module_registry, load_skill_registry, load_capabilities,
    get_module, get_skill, get_capability,
    get_enabled_modules, get_enabled_skills, get_enabled_capabilities,
    get_planned_modules, get_planned_skills,
    reload_all, get_registry_status,
)
from registry.validator import validate_all, generate_validation_report
from registry.schemas import ModuleSpec, SkillSpec, CapabilitySpec, ValidationResult
