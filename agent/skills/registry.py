# agent/skills/registry.py
"""SkillRegistry — load, search, and manage skill definitions."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from agent.skills.schemas import SkillSpec

_log = logging.getLogger(__name__)


class SkillRegistry:
    """Registry of reusable skill workflows."""

    def __init__(self):
        self._skills: dict[str, SkillSpec] = {}
        self._by_category: dict[str, list[str]] = {}

    # ── Registration ──

    def register(self, spec: SkillSpec) -> None:
        self._skills[spec.skill_id] = spec
        self._by_category.setdefault(spec.category, []).append(spec.skill_id)

    def unregister(self, skill_id: str) -> None:
        spec = self._skills.pop(skill_id, None)
        if spec:
            cat_list = self._by_category.get(spec.category, [])
            if skill_id in cat_list:
                cat_list.remove(skill_id)

    # ── Query ──

    def get(self, skill_id: str) -> Optional[SkillSpec]:
        return self._skills.get(skill_id)

    def list_all(self) -> list[SkillSpec]:
        return list(self._skills.values())

    def list_enabled(self) -> list[SkillSpec]:
        return [s for s in self._skills.values() if s.enabled]

    def search(self, query: str) -> list[SkillSpec]:
        lower = query.lower()
        results = []
        for s in self._skills.values():
            if not s.enabled:
                continue
            score = 0
            if lower in s.name.lower():
                score += 10
            if lower in s.description.lower():
                score += 5
            for kw in lower.split():
                if kw in s.name.lower():
                    score += 3
                for tool in s.tools_required:
                    if kw in tool.lower():
                        score += 2
            if score > 0:
                results.append((s, score))
        results.sort(key=lambda x: -x[1])
        return [r[0] for r in results[:10]]

    def count(self) -> int:
        return len(self._skills)

    def to_prompt_text(self) -> str:
        """Render all enabled skills as LLM prompt fragment."""
        skills = self.list_enabled()
        if not skills:
            return ""
        lines = ["--- SKILLS ---", f"{len(skills)} skills loaded:"]
        for s in sorted(skills, key=lambda x: x.category):
            lines.append(f"  [{s.category}] {s.name}: {s.description}")
        return "\n".join(lines)


# ── Loader ──


def load_skills_from_dir(
    registry: SkillRegistry,
    skills_dir: str,
) -> int:
    """Load all SKILL.md files from a directory into the registry.

    Returns number of skills loaded.
    """
    import re
    path = Path(skills_dir)
    if not path.exists():
        _log.info("Skills directory not found: %s", skills_dir)
        return 0

    loaded = 0
    for md_file in sorted(path.rglob("SKILL.md")):
        try:
            content = md_file.read_text(encoding="utf-8")
            spec = _parse_skill_md(content, str(md_file))
            if spec:
                registry.register(spec)
                loaded += 1
                _log.info("Loaded skill: %s from %s", spec.skill_id, md_file)
        except Exception as e:
            _log.warning("Failed to load skill from %s: %s", md_file, e)

    return loaded


def _parse_skill_md(content: str, path: str) -> Optional[SkillSpec]:
    """Parse SKILL.md content into a SkillSpec."""
    import re
    import yaml

    # Extract YAML frontmatter
    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    if not fm_match:
        return None

    try:
        fm = yaml.safe_load(fm_match.group(1))
    except Exception:
        return None

    if not isinstance(fm, dict):
        return None

    body = content[fm_match.end():].strip()

    # Parse steps from body
    steps = []
    step_pattern = re.compile(r"^##\s*Step\s*(\d+)\s*\n(.*?)(?=\n##|\Z)", re.DOTALL | re.MULTILINE)
    for m in step_pattern.finditer(body):
        step_num = m.group(1)
        step_body = m.group(2).strip()
        goal = ""
        tools = []
        for line in step_body.split("\n"):
            line = line.strip()
            if line.startswith("Goal:"):
                goal = line[5:].strip()
            elif line.startswith("Tools:"):
                tools = [t.strip() for t in line[6:].split(",") if t.strip()]
        steps.append({"step": int(step_num), "goal": goal, "tools": tools})

    return SkillSpec(
        skill_id=fm.get("id", fm.get("name", "unnamed").lower().replace(" ", "_")),
        name=fm.get("name", "Unnamed Skill"),
        description=fm.get("description", ""),
        version=str(fm.get("version", "1.0")),
        author=str(fm.get("author", "")),
        category=str(fm.get("category", "general")),
        tools_required=fm.get("tools", fm.get("tools_required", [])),
        steps=steps,
        example=str(fm.get("example", "")),
        markdown_path=path,
    )
