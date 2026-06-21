# agent/skills/registry.py
"""SkillRegistry — thin view over CapabilityRegistry.

SkillRegistry is not a parallel source of truth. It must be constructed with a
CapabilityRegistry and reads everything through it.
"""

from __future__ import annotations

from typing import List, Optional

from agent.capabilities.schemas import CapabilityManifest


class SkillRegistry:
    """Read-only view of capability skills, projected from CapabilityRegistry.

    The base/system skill `assistant_chat` is the only skill NOT carried
    by a Capability; we keep it in the view as an always-enabled base
    (so the LLM can always reply, even on a no-capability message).
    """

    BASE_SKILLS: tuple[str, ...] = ("assistant_chat",)

    def __init__(self, capability_registry):
        if capability_registry is None:
            raise ValueError(
                "SkillRegistry requires a CapabilityRegistry; "
                "there is no default. Construct via "
                "SkillRegistry(get_default_capability_registry()) or "
                "SkillRegistry.from_capabilities(cap_reg)."
            )
        self._cap_reg = capability_registry
        # Cache the base skill spec objects (if present) so
        # list_enabled_skills() / get_skill() can return them.
        self._base_skill_specs: dict[str, object] = {}
        for cap in capability_registry.list_all():
            for sk in cap.skills:
                if sk.skill_id in self.BASE_SKILLS:
                    # Capture the spec; later wins if duplicates.
                    self._base_skill_specs[sk.skill_id] = _skill_spec_from_capability(cap)
        # v1.0.3: ensure BASE_SKILLS that are NOT from any capability
        # (e.g. assistant_chat) are always available as enabled.
        for bs in self.BASE_SKILLS:
            if bs not in self._base_skill_specs:
                self._base_skill_specs[bs] = _base_skill_spec(bs)

    # ── Read ──

    def list_enabled_skills(self) -> list:
        """Return enabled skills. Order: base skills first, then capability skills."""
        out: list = []
        seen: set[str] = set()
        # 1. Base skills
        for s in self.BASE_SKILLS:
            spec = self._base_skill_specs.get(s)
            if spec and getattr(spec, "status", "disabled") == "enabled":
                out.append(spec)
                seen.add(s)
        # 2. Capability skills (status == enabled)
        for cap in self._cap_reg.list_enabled():
            for sk in cap.skills:
                if sk.status != "enabled":
                    continue
                if sk.skill_id in seen:
                    continue
                out.append(_skill_spec_from_capability(cap))
                seen.add(sk.skill_id)
        return out

    def list_planned_skills(self) -> list:
        out: list = []
        for cap in self._cap_reg.list_planned():
            for sk in cap.skills:
                if sk.status != "planned":
                    continue
                out.append(_skill_spec_from_capability(cap))
        return out

    def get_skill(self, skill_id: str):
        # Base skill lookup
        if skill_id in self._base_skill_specs:
            return self._base_skill_specs[skill_id]
        # Capability skill lookup (first match wins)
        for cap in self._cap_reg.list_all():
            for sk in cap.skills:
                if sk.skill_id == skill_id:
                    return _skill_spec_from_capability(cap)
        return None

    def snapshot(self) -> dict:
        return {
            "enabled": [
                {"skill_id": s.skill_id, "name": s.name, "prompt_summary": s.prompt_summary}
                for s in self.list_enabled_skills()
            ],
            "planned": [
                {"skill_id": s.skill_id, "name": s.name}
                for s in self.list_planned_skills()
            ],
        }

    # ── Construction helpers ──

    @classmethod
    def from_capabilities(cls, capability_registry) -> "SkillRegistry":
        """Build a SkillRegistry from a CapabilityRegistry."""
        return cls(capability_registry)

    @property
    def capability_registry(self):
        return self._cap_reg


def _skill_spec_from_capability(cap: CapabilityManifest):
    """Return a SkillSpec-shaped object for a CapabilityManifest.

    CapabilityManifest may carry multiple skills; we expose a tiny
    shim with the first matching skill's data. Compatibility callers
    read .skill_id / .name / .prompt_summary / .status / .related_tools
    / .module_id, all of which we populate from the capability.
    """
    sk = cap.skills[0] if cap.skills else None
    return _SkillSpecShim(
        skill_id=sk.skill_id if sk else cap.capability_id,
        name=cap.name,
        description=cap.description,
        status=sk.status if sk else cap.module.status,
        related_tools=list(sk.related_tools) if sk else [t.tool_id for t in cap.tools],
        prompt_summary=sk.prompt_summary if sk else cap.description,
        module_id=cap.module.module_id,
    )


class _SkillSpecShim:
    __slots__ = ("skill_id", "name", "description", "status",
                 "related_tools", "prompt_summary", "module_id")

    def __init__(self, *, skill_id, name, description, status,
                 related_tools, prompt_summary, module_id):
        self.skill_id = skill_id
        self.name = name
        self.description = description
        self.status = status
        self.related_tools = related_tools
        self.prompt_summary = prompt_summary
        self.module_id = module_id


def _base_skill_spec(skill_id: str) -> "_SkillSpecShim":
    """Create a SkillSpecShim for a base skill (e.g. assistant_chat)
    that does NOT come from any CapabilityManifest.
    """
    base_specs = {
        "assistant_chat": {
            "name": "Assistant Chat",
            "description": "General-purpose chat without capability tools.",
            "prompt_summary": "General assistant chat — no specific capability",
        },
        "capability_discovery": {
            "name": "Capability Discovery",
            "description": "Help users discover and understand available capabilities.",
            "prompt_summary": "Capability discovery and explanation",
        },
    }
    info = base_specs.get(skill_id, {
        "name": skill_id,
        "description": f"Base skill: {skill_id}",
        "prompt_summary": f"Base skill: {skill_id}",
    })
    return _SkillSpecShim(
        skill_id=skill_id,
        name=info["name"],
        description=info["description"],
        status="enabled",
        related_tools=[],
        prompt_summary=info["prompt_summary"],
        module_id="",
    )
