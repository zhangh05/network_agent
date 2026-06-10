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
