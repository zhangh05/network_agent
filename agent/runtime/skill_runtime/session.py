# agent/runtime/skill_runtime/session.py
"""Skill session — lightweight record for active skills in a turn."""

from __future__ import annotations

from typing import Any


def skill_session_record(load_result) -> dict[str, Any]:
    """Build a session-scoped record from a SkillLoadResult."""
    return {
        "skill_id": load_result.skill_id,
        "status": load_result.status,
        "capability_ids": list(load_result.capability_ids),
        "module_ids": list(load_result.module_ids),
        "tool_ids": list(load_result.tool_ids),
        "prompt_hints": list(load_result.prompt_hints),
        "safety_notes": list(load_result.safety_notes),
    }
