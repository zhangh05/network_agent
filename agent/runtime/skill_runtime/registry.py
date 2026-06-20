# agent/runtime/skill_runtime/registry.py
"""Skill registry — generates SkillManifest from CapabilityPackage definitions.

CapabilityPackage is the authoritative built-in skill definition.
"""

from __future__ import annotations

from agent.runtime.capability_routing.manifests import CAPABILITY_PACKAGES
from agent.runtime.skill_runtime.models import SkillManifest


def builtin_skill_manifests() -> dict[str, SkillManifest]:
    """Build SkillManifest entries from all registered CapabilityPackages."""
    manifests = {}
    for pkg in CAPABILITY_PACKAGES:
        manifests[pkg.capability_id] = SkillManifest(
            skill_id=pkg.capability_id,
            display_name=pkg.display_name,
            description=pkg.description,
            status="active",
            capability_ids=(pkg.capability_id,),
            module_ids=tuple(pkg.module_ids),
            tool_ids=tuple(pkg.tool_ids),
            prompt_hints=tuple(pkg.prompt_hints),
            safety_notes=tuple(pkg.safety_notes),
            output_kinds=tuple(pkg.output_kinds),
            source="capability_package",
        )
    return manifests


def list_skill_manifests() -> list[SkillManifest]:
    """Return all built-in skill manifests, sorted by skill_id."""
    return sorted(
        builtin_skill_manifests().values(),
        key=lambda item: item.skill_id,
    )


def get_skill_manifest(skill_id: str) -> SkillManifest | None:
    """Look up a single skill manifest by ID."""
    return builtin_skill_manifests().get(skill_id)


def search_skill_manifests(query: str, limit: int = 10) -> list[SkillManifest]:
    """Search skill manifests by keyword match."""
    q = (query or "").lower().strip()
    if not q:
        return []
    scored = []
    for manifest in list_skill_manifests():
        haystack = " ".join([
            manifest.skill_id,
            manifest.display_name,
            manifest.description,
            " ".join(manifest.capability_ids),
            " ".join(manifest.module_ids),
            " ".join(manifest.tool_ids),
        ]).lower()
        if q in haystack:
            scored.append(manifest)
    return scored[:max(1, min(limit, 20))]
