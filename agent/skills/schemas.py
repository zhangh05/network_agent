# agent/skills/schemas.py
"""Skill system schemas — SKILL.md open standard (agentskills.io compatible)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SkillSpec:
    """A reusable skill definition loaded from SKILL.md."""

    skill_id: str
    name: str
    description: str
    version: str = "1.0"
    author: str = ""
    category: str = "general"
    tools_required: list[str] = field(default_factory=list)
    steps: list[dict] = field(default_factory=list)
    example: str = ""
    markdown_path: str = ""
    enabled: bool = True

    def to_prompt(self) -> str:
        lines = [
            f"## Skill: {self.name} ({self.skill_id})",
            f"Description: {self.description}",
            f"Required tools: {', '.join(self.tools_required)}",
        ]
        if self.steps:
            lines.append("Steps:")
            for i, s in enumerate(self.steps, 1):
                lines.append(f"  {i}. {s.get('goal', '')} → {', '.join(s.get('tools', []))}")
        if self.example:
            lines.append(f"Example: {self.example}")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "category": self.category,
            "tools_required": self.tools_required,
            "enabled": self.enabled,
        }
