# agent/runtime/tasking/models.py
"""Task-flow dataclasses for planning, execution, and progress."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import List, Optional


def _tid() -> str:
    return f"task_{uuid.uuid4().hex[:12]}"


def _wfid() -> str:
    return f"wf_{uuid.uuid4().hex[:12]}"


def _stepid() -> str:
    return f"step_{uuid.uuid4().hex[:12]}"


@dataclass
class TaskSignal:
    """Output of TaskDetector — what does the user want to do?"""
    kind: str = "none"  # new_task/continue_task/update_task/cancel_task/none
    confidence: float = 0.0
    reason: str = ""
    referenced_task_id: Optional[str] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class TaskPlan:
    """High-level plan for a task."""
    task_id: str = field(default_factory=_tid)
    title: str = ""
    user_goal: str = ""
    steps: List[str] = field(default_factory=list)
    completion_criteria: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class StepPlan:
    """Plan for a single workflow step."""
    step_id: str = field(default_factory=_stepid)
    task_id: str = ""
    title: str = ""
    goal: str = ""
    order: int = 0
    required_evidence: List[str] = field(default_factory=list)
    required_actions: List[str] = field(default_factory=list)
    completion_check: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class WorkflowPlan:
    """Full workflow plan with ordered steps."""
    workflow_id: str = field(default_factory=_wfid)
    task_id: str = ""
    steps: List[StepPlan] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class StepResult:
    """Result of executing a step."""
    step_id: str = ""
    task_id: str = ""
    status: str = "completed"  # completed/failed/blocked/skipped
    summary: str = ""
    action_ids: List[str] = field(default_factory=list)
    artifact_ids: List[str] = field(default_factory=list)
    error: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class TaskProgress:
    """Current progress summary for a task."""
    task_id: str = ""
    current_step_id: Optional[str] = None
    completed_steps: int = 0
    total_steps: int = 0
    progress_percent: float = 0.0
    status: str = ""
    metadata: dict = field(default_factory=dict)
