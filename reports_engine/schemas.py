# reports_engine/schemas.py
"""ReportRequest, ReportSection, ReportDocument, ExportResult schemas."""

import uuid, time
from dataclasses import dataclass, field
from typing import Optional

VALID_REPORT_TYPES = {"config_translation", "inspection", "topology", "knowledge", "generic"}
VALID_FORMATS = {"markdown", "html", "json", "csv", "docx", "pdf"}


@dataclass
class ReportRequest:
    workspace_id: str = "default"
    run_id: Optional[str] = None
    report_type: str = "config_translation"
    source: str = "agent_result"
    source_run_id: Optional[str] = None
    source_artifact_ids: list = field(default_factory=list)
    title: str = ""
    format: str = "markdown"
    sensitivity: str = "internal"
    include_sections: list = field(default_factory=list)
    include_deployable_config: bool = False
    options: dict = field(default_factory=dict)
    created_by: str = "agent"


@dataclass
class ReportSection:
    section_id: str = ""
    title: str = ""
    level: int = 1
    content: str = ""
    content_type: str = "markdown"
    sensitivity: str = "internal"
    metadata: dict = field(default_factory=dict)


@dataclass
class ReportDocument:
    report_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    workspace_id: str = "default"
    run_id: Optional[str] = None
    report_type: str = "generic"
    title: str = ""
    format: str = "markdown"
    sections: list = field(default_factory=list)
    source_artifacts: list = field(default_factory=list)
    source_run_id: Optional[str] = None
    sensitivity: str = "internal"
    summary: str = ""
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))
    metadata: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "report_id": self.report_id, "workspace_id": self.workspace_id,
            "run_id": self.run_id, "report_type": self.report_type,
            "title": self.title, "format": self.format,
            "sections": [self._section_dict(s) for s in self.sections],
            "source_artifacts": self.source_artifacts,
            "source_run_id": self.source_run_id,
            "sensitivity": self.sensitivity, "summary": self.summary,
            "created_at": self.created_at, "metadata": self.metadata,
        }

    def _section_dict(self, s):
        if isinstance(s, dict): return s
        return {"section_id": s.section_id, "title": s.title, "level": s.level,
                "content": s.content, "content_type": s.content_type,
                "sensitivity": s.sensitivity}


@dataclass
class ExportResult:
    ok: bool = True
    report_id: str = ""
    artifact_id: str = ""
    workspace_id: str = ""
    run_id: Optional[str] = None
    format: str = ""
    path: str = ""
    sensitivity: str = "internal"
    summary: str = ""
    size_bytes: int = 0
    sha256: str = ""
    warnings: list = field(default_factory=list)
    error: str = ""

    def as_dict(self) -> dict:
        return {
            "ok": self.ok, "report_id": self.report_id,
            "artifact_id": self.artifact_id, "workspace_id": self.workspace_id,
            "run_id": self.run_id, "format": self.format,
            "sensitivity": self.sensitivity, "summary": self.summary,
            "size_bytes": self.size_bytes, "sha256_short": self.sha256[:12] if self.sha256 else "",
            "warnings": self.warnings, "error": self.error,
        }
