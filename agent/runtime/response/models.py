# agent/runtime/response/models.py
"""Data models for the Response Composer / Final Answer Kernel."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ResponsePlan:
    response_type: str = "answer"  # answer/progress/artifact/approval/blocked/failed/clarify
    task_id: str = ""
    step_id: str = ""
    status: str = ""
    main_points: list[str] = field(default_factory=list)
    artifact_ids: list[str] = field(default_factory=list)
    pending_approvals: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class FinalResponse:
    content: str = ""
    response_type: str = ""
    artifact_ids: list[str] = field(default_factory=list)
    task_id: str = ""
    step_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
