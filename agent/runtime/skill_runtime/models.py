# agent/runtime/skill_runtime/models.py
"""Data models for the capability-first skill runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SkillManifest:
    """Capability-first skill declaration. Does NOT store prompt content."""

    skill_id: str
    display_name: str
    description: str
    status: str
    capability_ids: tuple[str, ...]
    module_ids: tuple[str, ...]
    tool_ids: tuple[str, ...]
    prompt_hints: tuple[str, ...] = ()
    safety_notes: tuple[str, ...] = ()
    output_kinds: tuple[str, ...] = ()
    source: str = "builtin"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SkillLoadResult:
    """Result of loading a skill — returns capability contract, NOT prompt content."""

    ok: bool
    skill_id: str
    status: str
    capability_ids: tuple[str, ...] = ()
    module_ids: tuple[str, ...] = ()
    tool_ids: tuple[str, ...] = ()
    prompt_hints: tuple[str, ...] = ()
    safety_notes: tuple[str, ...] = ()
    message: str = ""
