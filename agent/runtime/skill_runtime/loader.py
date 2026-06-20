# agent/runtime/skill_runtime/loader.py
"""Skill loader — returns capability contract, NOT prompt content."""

from __future__ import annotations

from agent.runtime.skill_runtime.models import SkillLoadResult
from agent.runtime.skill_runtime.registry import get_skill_manifest


def load_skill(skill_id: str) -> SkillLoadResult:
    """Load a skill by ID and return its capability contract.

    Does NOT read SKILL.md.
    Does NOT inject system prompt.
    Returns capability_ids, module_ids, tool_ids, prompt_hints, safety_notes.
    """
    manifest = get_skill_manifest(skill_id)
    if manifest is None:
        return SkillLoadResult(
            ok=False,
            skill_id=skill_id,
            status="not_found",
            message=f"skill '{skill_id}' not found",
        )
    if manifest.status != "active":
        return SkillLoadResult(
            ok=False,
            skill_id=skill_id,
            status=manifest.status,
            message=f"skill '{skill_id}' is not active",
        )
    return SkillLoadResult(
        ok=True,
        skill_id=manifest.skill_id,
        status=manifest.status,
        capability_ids=manifest.capability_ids,
        module_ids=manifest.module_ids,
        tool_ids=manifest.tool_ids,
        prompt_hints=manifest.prompt_hints,
        safety_notes=manifest.safety_notes,
        message="skill loaded as capability package",
    )
