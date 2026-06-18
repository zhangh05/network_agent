# memory/schemas.py
"""Memory, Run, Workspace, and Artifact schema definitions."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


# ─── Confidence enum replaces float ───
CONFIDENCE_VALUES = ("system_generated", "user_confirmed", "inferred", "imported")

# ─── Sensitivity levels ───
SENSITIVITY_VALUES = ("public", "internal", "sensitive")

# ─── Memory types ───
MEMORY_TYPES = (
    "user_preference", "project_state", "decision",
    "translation_rule", "device_profile", "troubleshooting_case",
    "run_summary", "knowledge_note",
)

# ─── Scopes ───
SCOPES = ("short_term", "project", "long_term")


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _normalize_confidence(value) -> str:
    """Normalize old float confidence to enum string."""
    if isinstance(value, str) and value in CONFIDENCE_VALUES:
        return value
    if isinstance(value, (int, float)):
        if value >= 0.8:
            return "system_generated"
        elif value >= 0.5:
            return "inferred"
        elif value >= 0.2:
            return "imported"
    return "system_generated"


def _now_isoformat_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


# ═══════════════════════════════════════════════════════════
# MemoryRecord — Agent memory schema
# ═══════════════════════════════════════════════════════════
@dataclass
class MemoryRecord:
    memory_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    scope: str = "short_term"        # short_term | project | long_term
    memory_type: str = "knowledge_note"
    title: str = ""
    summary: str = ""
    content: str = ""
    tags: list = field(default_factory=list)
    project_id: Optional[str] = ""
    source: str = ""                 # agent | user | system | user_confirmed
    confidence: str = "system_generated"  # system_generated | user_confirmed | inferred | imported
    sensitivity: str = "internal"    # public | internal | sensitive
    created_at: str = field(default_factory=_utcnow)
    updated_at: str = field(default_factory=_utcnow)
    expires_at: Optional[str] = None
    metadata: dict = field(default_factory=dict)
    redaction_applied: bool = False

    def as_dict(self) -> dict:
        return {
            "memory_id": self.memory_id,
            "scope": self.scope,
            "memory_type": self.memory_type,
            "title": self.title,
            "summary": self.summary,
            "content": self.content,
            "tags": self.tags,
            "project_id": self.project_id,
            "source": self.source,
            "confidence": self.confidence,
            "sensitivity": self.sensitivity,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "expires_at": self.expires_at,
            "metadata": self.metadata,
            "redaction_applied": self.redaction_applied,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MemoryRecord":
        confidence = _normalize_confidence(data.get("confidence", "system_generated"))
        return cls(
            memory_id=data.get("memory_id", str(uuid.uuid4())[:8]),
            scope=data.get("scope", "short_term"),
            memory_type=data.get("memory_type", "knowledge_note"),
            title=data.get("title", ""),
            summary=data.get("summary", ""),
            content=data.get("content", ""),
            tags=data.get("tags", []),
            project_id=data.get("project_id", ""),
            source=data.get("source", ""),
            confidence=confidence,
            sensitivity=data.get("sensitivity", "internal"),
            created_at=data.get("created_at", _utcnow()),
            updated_at=data.get("updated_at", _utcnow()),
            expires_at=data.get("expires_at"),
            metadata=data.get("metadata", {}),
            redaction_applied=data.get("redaction_applied", False),
        )


# ═══════════════════════════════════════════════════════════
# RunRecord — Agent run history
# ═══════════════════════════════════════════════════════════
@dataclass
class RunRecord:
    run_id: str = ""
    workspace_id: str = ""
    request_id: str = ""
    user_input_summary: str = ""
    intent: str = ""
    active_module: str = ""
    selected_skill: str = ""
    runtime_mode: str = ""
    started_at: str = ""
    finished_at: str = ""
    status: str = "ok"              # ok | error
    result_counts: dict = field(default_factory=dict)
    verification: dict = field(default_factory=dict)
    llm_metadata: dict = field(default_factory=dict)
    memory_written: bool = False
    workspace_updated: bool = False
    artifacts: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    error: Optional[str] = None
    sensitivity: str = "internal"
    redaction_applied: bool = False

    def as_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "workspace_id": self.workspace_id,
            "request_id": self.request_id,
            "user_input_summary": self.user_input_summary,
            "intent": self.intent,
            "active_module": self.active_module,
            "selected_skill": self.selected_skill,
            "runtime_mode": self.runtime_mode,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "status": self.status,
            "result_counts": self.result_counts,
            "verification": self.verification,
            "llm_metadata": self.llm_metadata,
            "memory_written": self.memory_written,
            "workspace_updated": self.workspace_updated,
            "artifacts": self.artifacts,
            "warnings": self.warnings,
            "error": self.error,
            "sensitivity": self.sensitivity,
            "redaction_applied": self.redaction_applied,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RunRecord":
        return cls(
            run_id=data.get("run_id", ""),
            workspace_id=data.get("workspace_id", ""),
            request_id=data.get("request_id", ""),
            user_input_summary=data.get("user_input_summary", ""),
            intent=data.get("intent", ""),
            active_module=data.get("active_module", ""),
            selected_skill=data.get("selected_skill", ""),
            runtime_mode=data.get("runtime_mode", ""),
            started_at=data.get("started_at", ""),
            finished_at=data.get("finished_at", ""),
            status=data.get("status", "ok"),
            result_counts=data.get("result_counts", {}),
            verification=data.get("verification", {}),
            llm_metadata=data.get("llm_metadata", {}),
            memory_written=data.get("memory_written", False),
            workspace_updated=data.get("workspace_updated", False),
            artifacts=data.get("artifacts", []),
            warnings=data.get("warnings", []),
            error=data.get("error"),
            sensitivity=data.get("sensitivity", "internal"),
            redaction_applied=data.get("redaction_applied", False),
        )


# ═══════════════════════════════════════════════════════════
# WorkspaceState
# ═══════════════════════════════════════════════════════════
@dataclass
class WorkspaceState:
    workspace_id: str = ""
    name: str = ""
    active_module: str = ""
    last_run_id: str = ""
    last_intent: str = ""
    last_active_module: str = ""
    last_result_summary: str = ""
    last_result_counts: dict = field(default_factory=dict)
    last_manual_review_samples: list = field(default_factory=list)
    last_unsupported_samples: list = field(default_factory=list)
    last_audit_summary: dict = field(default_factory=dict)
    current_files: list = field(default_factory=list)
    current_artifacts: list = field(default_factory=list)
    llm_metadata: dict = field(default_factory=dict)
    runs_count: int = 0
    memory_count: int = 0
    artifacts_count: int = 0
    updated_at: str = ""

    def as_dict(self) -> dict:
        return {
            "workspace_id": self.workspace_id,
            "name": self.name,
            "active_module": self.active_module,
            "last_run_id": self.last_run_id,
            "last_intent": self.last_intent,
            "last_active_module": self.last_active_module,
            "last_result_summary": self.last_result_summary,
            "last_result_counts": self.last_result_counts,
            "last_manual_review_samples": self.last_manual_review_samples,
            "last_unsupported_samples": self.last_unsupported_samples,
            "last_audit_summary": self.last_audit_summary,
            "current_files": self.current_files,
            "current_artifacts": self.current_artifacts,
            "llm_metadata": self.llm_metadata,
            "runs_count": self.runs_count,
            "memory_count": self.memory_count,
            "artifacts_count": self.artifacts_count,
            "updated_at": self.updated_at,
        }


# ═══════════════════════════════════════════════════════════
# ArtifactRecord
# ═══════════════════════════════════════════════════════════
@dataclass
class ArtifactRecord:
    artifact_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    workspace_id: str = ""
    run_id: str = ""
    artifact_type: str = ""         # input | output | report | temp
    path: str = ""
    title: str = ""
    summary: str = ""
    sensitivity: str = "internal"
    created_at: str = field(default_factory=_utcnow)
    metadata: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "artifact_id": self.artifact_id,
            "workspace_id": self.workspace_id,
            "run_id": self.run_id,
            "artifact_type": self.artifact_type,
            "path": self.path,
            "title": self.title,
            "summary": self.summary,
            "sensitivity": self.sensitivity,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ArtifactRecord":
        return cls(
            artifact_id=data.get("artifact_id", ""),
            workspace_id=data.get("workspace_id", ""),
            run_id=data.get("run_id", ""),
            artifact_type=data.get("artifact_type", ""),
            path=data.get("path", ""),
            title=data.get("title", ""),
            summary=data.get("summary", ""),
            sensitivity=data.get("sensitivity", "internal"),
            created_at=data.get("created_at", _utcnow()),
            metadata=data.get("metadata", {}),
        )
