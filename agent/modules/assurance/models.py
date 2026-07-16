"""Durable data contracts for Network Assurance."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent.runtime.utils import now_iso


@dataclass
class NormalizedFact:
    key: str
    value: Any
    asset_id: str = ""
    category: str = "state"
    evidence_ref: str = ""
    observed_at: str = ""


@dataclass
class StateSnapshot:
    snapshot_id: str
    workspace_id: str
    scope: dict[str, Any]
    inspection_task_id: str
    source_status: str
    facts: list[dict[str, Any]] = field(default_factory=list)
    asset_count: int = 0
    created_at: str = field(default_factory=now_iso)


@dataclass
class AssuranceBaseline:
    baseline_id: str
    workspace_id: str
    name: str
    scope: dict[str, Any]
    snapshot_id: str
    source_task_id: str
    status: str = "active"
    fact_count: int = 0
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)


@dataclass
class BaselineCheck:
    check_id: str
    workspace_id: str
    baseline_id: str
    scope: dict[str, Any]
    inspection_task_id: str
    status: str = "collecting"
    drift_id: str = ""
    error: str = ""
    total_assets: int = 0
    completed_assets: int = 0
    succeeded_assets: int = 0
    failed_assets: int = 0
    partial_assets: int = 0
    artifact_ids: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    finished_at: str = ""


@dataclass
class AssuranceOperation:
    operation_id: str
    workspace_id: str
    kind: str
    ref_id: str
    scope: dict[str, Any]
    inspection_task_id: str
    status: str = "collecting"
    phase: str = "collecting_evidence"
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    total_assets: int = 0
    completed_assets: int = 0
    succeeded_assets: int = 0
    failed_assets: int = 0
    partial_assets: int = 0
    artifact_ids: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    finished_at: str = ""


@dataclass
class DriftRecord:
    drift_id: str
    workspace_id: str
    baseline_id: str
    snapshot_id: str
    source_task_id: str
    status: str
    changes: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)
    incomplete: bool = False
    created_at: str = field(default_factory=now_iso)


@dataclass
class TopologySnapshot:
    topology_id: str
    workspace_id: str
    nodes: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)
    source_task_id: str = ""
    created_at: str = field(default_factory=now_iso)


@dataclass
class IncidentRecord:
    incident_id: str
    workspace_id: str
    title: str
    symptom: str
    scope: dict[str, Any]
    status: str = "investigating"
    severity: str = "warning"
    drift_id: str = ""
    hypotheses: list[dict[str, Any]] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    affected_assets: list[str] = field(default_factory=list)
    conclusion: str = ""
    next_actions: list[str] = field(default_factory=list)
    operation_id: str = ""
    inspection_task_id: str = ""
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)


@dataclass
class ChangePlan:
    change_id: str
    workspace_id: str
    title: str
    summary: str
    asset_ids: list[str]
    status: str = "draft"
    risk_level: str = "medium"
    prechecks: list[str] = field(default_factory=list)
    postchecks: list[str] = field(default_factory=list)
    rollback_conditions: list[str] = field(default_factory=list)
    impact: dict[str, Any] = field(default_factory=dict)
    validation: dict[str, Any] = field(default_factory=dict)
    precheck_operation_id: str = ""
    postcheck_operation_id: str = ""
    pre_snapshot_id: str = ""
    post_snapshot_id: str = ""
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)


@dataclass
class AssuranceSchedule:
    schedule_id: str
    workspace_id: str
    name: str
    baseline_id: str
    scope: dict[str, Any]
    interval_minutes: int
    enabled: bool = True
    next_run_at: str = ""
    last_run_at: str = ""
    last_task_id: str = ""
    last_drift_id: str = ""
    state: str = "idle"
    error: str = ""
    run_count: int = 0
    consecutive_failures: int = 0
    last_status: str = ""
    last_artifact_ids: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
