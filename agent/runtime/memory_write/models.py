# agent/runtime/memory_write/models.py
"""Data models for the Memory Writer / Learning Kernel."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MemoryCandidate:
    candidate_id: str = ""
    memory_type: str = ""  # user_preference/task_pattern/tool_learning/error_lesson/artifact_summary
    content: str = ""
    source: str = ""  # task/action/artifact/response/user
    task_id: str = ""
    confidence: float = 0.0
    risk_level: str = "low"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MemoryWritePlan:
    task_id: str = ""
    candidates: list[MemoryCandidate] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
