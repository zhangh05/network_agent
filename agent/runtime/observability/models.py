# agent/runtime/observability/models.py
"""Data models for the Inspector / Observability Kernel."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ObservabilityEvent:
    event_id: str = ""
    event_type: str = ""  # scene/context/tool/action/task/output/response/memory/error
    turn_id: str = ""
    task_id: str = ""
    step_id: str = ""
    action_id: str = ""
    status: str = ""
    summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TurnTrace:
    turn_id: str = ""
    session_id: str = ""
    task_id: str = ""
    step_id: str = ""
    events: list[ObservabilityEvent] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
