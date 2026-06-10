# agent/skills/registry.py
"""SkillRegistry — manages enabled/planned skills."""

from agent.skills.schemas import (
    SkillSpec, SKILL_CONFIG_TRANSLATION, SKILL_ASSISTANT_CHAT,
    SKILL_KNOWLEDGE, SKILL_TOPOLOGY, SKILL_INSPECTION, SKILL_CMDB,
)


class SkillRegistry:
    def __init__(self):
        self._skills: dict = {}
        self._register_defaults()

    def _register_defaults(self):
        defaults = [
            SKILL_ASSISTANT_CHAT, SKILL_CONFIG_TRANSLATION, SKILL_KNOWLEDGE,
            SKILL_TOPOLOGY, SKILL_INSPECTION, SKILL_CMDB,
        ]
        for s in defaults:
            self._skills[s.skill_id] = s

    def list_enabled_skills(self) -> list:
        return [s for s in self._skills.values() if s.status == "enabled"]

    def list_planned_skills(self) -> list:
        return [s for s in self._skills.values() if s.status == "planned"]

    def get_skill(self, skill_id: str) -> SkillSpec:
        return self._skills.get(skill_id)

    def snapshot(self) -> dict:
        return {
            "enabled": [{"skill_id": s.skill_id, "name": s.name, "prompt_summary": s.prompt_summary}
                        for s in self.list_enabled_skills()],
            "planned": [{"skill_id": s.skill_id, "name": s.name}
                        for s in self.list_planned_skills()],
        }

    @classmethod
    def from_capabilities(cls, capability_registry, base_skill_registry: "SkillRegistry | None" = None) -> "SkillRegistry":
        """Build a SkillRegistry from a CapabilityRegistry.

        Project each enabled / planned capability's skill specs into
        legacy SkillSpec records. `assistant_chat` is the system /
        base skill and is kept from the defaults; it is NOT carried
        by a Capability.

        Falls back to defaults if capability_registry is None.
        """
        reg = cls() if base_skill_registry is None else base_skill_registry
        if capability_registry is None:
            return reg
        # Preserve the base/system skill (assistant_chat) if it was registered.
        for s in list(reg._skills.values()):
            if s.skill_id == "assistant_chat" and s.status == "enabled":
                # Always keep assistant_chat in the enabled view.
                pass
        # Add capability-derived skills.
        for cap in capability_registry.list_all():
            for s in cap.skills:
                reg._skills[s.skill_id] = SkillSpec(
                    skill_id=s.skill_id,
                    name=cap.name,
                    description=cap.description,
                    status=s.status,
                    related_tools=list(s.related_tools),
                    prompt_summary=s.prompt_summary,
                    module_id=cap.module.module_id,
                )
        return reg
