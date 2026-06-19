# agent/runtime/state/models.py
"""Runtime state dataclasses for task workflow tracking."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, List, Optional


def _sid() -> str:
    return f"sess_{uuid.uuid4().hex[:12]}"


def _wid() -> str:
    return f"ws_{uuid.uuid4().hex[:12]}"


def _tid() -> str:
    return f"task_{uuid.uuid4().hex[:12]}"


def _wfid() -> str:
    return f"wf_{uuid.uuid4().hex[:12]}"


def _stepid() -> str:
    return f"step_{uuid.uuid4().hex[:12]}"


def _artid() -> str:
    return f"art_{uuid.uuid4().hex[:12]}"


def _actid() -> str:
    return f"act_{uuid.uuid4().hex[:12]}"


# ── Session ─────────────────────────────────────────────────────────────


@dataclass
class SessionState:
    session_id: str = field(default_factory=_sid)
    active_task_id: Optional[str] = None
    last_task_id: Optional[str] = None
    turn_count: int = 0
    metadata: dict = field(default_factory=dict)


# ── Workspace ───────────────────────────────────────────────────────────


@dataclass
class WorkspaceState:
    workspace_id: str = field(default_factory=_wid)
    root_path: str = ""
    active_artifact_ids: List[str] = field(default_factory=list)
    recent_artifact_ids: List[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


# ── Artifact ────────────────────────────────────────────────────────────


@dataclass
class ArtifactState:
    artifact_id: str = field(default_factory=_artid)
    task_id: str = ""
    step_id: str = ""
    kind: str = ""
    path: str = ""
    summary: str = ""
    status: str = "created"
    metadata: dict = field(default_factory=dict)


# ── Action ──────────────────────────────────────────────────────────────


@dataclass
class ActionState:
    action_id: str = field(default_factory=_actid)
    task_id: str = ""
    step_id: str = ""
    tool_id: str = ""
    action_class: str = "unknown"
    risk_level: str = "low"
    status: str = "pending"
    summary: str = ""
    metadata: dict = field(default_factory=dict)


# ── Step ────────────────────────────────────────────────────────────────


@dataclass
class StepState:
    step_id: str = field(default_factory=_stepid)
    task_id: str = ""
    title: str = ""
    goal: str = ""
    status: str = "pending"  # pending/running/completed/failed/blocked/approval_pending/skipped
    order: int = 0
    required_evidence: List[str] = field(default_factory=list)
    required_actions: List[str] = field(default_factory=list)
    artifact_ids: List[str] = field(default_factory=list)
    action_ids: List[str] = field(default_factory=list)
    result_summary: str = ""
    error: str = ""
    blocked_reason: str = ""
    completion_check: str = ""
    metadata: dict = field(default_factory=dict)


# ── Workflow ────────────────────────────────────────────────────────────


@dataclass
class WorkflowState:
    workflow_id: str = field(default_factory=_wfid)
    task_id: str = ""
    status: str = "pending"  # pending/running/completed/failed/blocked/paused
    current_step_id: Optional[str] = None
    steps: List[StepState] = field(default_factory=list)
    progress_percent: float = 0.0
    metadata: dict = field(default_factory=dict)


# ── Task ────────────────────────────────────────────────────────────────


@dataclass
class TaskState:
    task_id: str = field(default_factory=_tid)
    title: str = ""
    user_goal: str = ""
    status: str = "pending"  # pending/running/completed/failed/blocked/paused/approval_pending
    priority: int = 0
    workflow_id: Optional[str] = None
    current_step_id: Optional[str] = None
    artifact_ids: List[str] = field(default_factory=list)
    action_ids: List[str] = field(default_factory=list)
    completion_criteria: str = ""
    progress_percent: float = 0.0
    created_turn_id: str = ""
    updated_turn_id: str = ""
    result_summary: str = ""
    failure_reason: str = ""
    metadata: dict = field(default_factory=dict)


# ── RuntimeState (aggregate root) ──────────────────────────────────────


@dataclass
class RuntimeState:
    session: SessionState = field(default_factory=SessionState)
    workspace: WorkspaceState = field(default_factory=WorkspaceState)
    active_task: Optional[TaskState] = None
    active_workflow: Optional[WorkflowState] = None
    tasks: List[TaskState] = field(default_factory=list)
    workflows: List[WorkflowState] = field(default_factory=list)
    artifacts: List[ArtifactState] = field(default_factory=list)
    actions: List[ActionState] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


# ── Snapshot ────────────────────────────────────────────────────────────


@dataclass
class RuntimeStateSnapshot:
    turn_id: str = ""
    session_id: str = ""
    workspace_id: str = ""
    active_task_id: Optional[str] = None
    active_step_id: Optional[str] = None
    task_status: str = ""
    workflow_status: str = ""
    progress_percent: float = 0.0
    pending_approvals: List[str] = field(default_factory=list)
    recent_actions: List[str] = field(default_factory=list)
    recent_artifacts: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
