# agent/runtime/skill_runtime/__init__.py
"""Skill runtime — capability-first skill management."""

from agent.runtime.skill_runtime.models import SkillManifest, SkillLoadResult
from agent.runtime.skill_runtime.registry import (
    builtin_skill_manifests,
    list_skill_manifests,
    get_skill_manifest,
    search_skill_manifests,
)
from agent.runtime.skill_runtime.loader import load_skill
from agent.runtime.skill_runtime.session import skill_session_record

__all__ = [
    "SkillManifest",
    "SkillLoadResult",
    "builtin_skill_manifests",
    "list_skill_manifests",
    "get_skill_manifest",
    "search_skill_manifests",
    "load_skill",
    "skill_session_record",
]
