# backend/api/skills.py
"""Skills API — data from registry loader."""

from flask import jsonify
from registry.loader import load_skill_registry


def handle_skills():
    skills = load_skill_registry()
    return jsonify({
        "skills": [
            {
                "skill_name": s.skill_name,
                "display_name": s.display_name,
                "status": s.status,
                "module": s.module,
                "capabilities": s.capabilities,
                "enabled": s.is_enabled(),
                "planned": s.is_planned(),
            }
            for s in skills
        ]
    })


def get_skill_count() -> int:
    return len(load_skill_registry())
