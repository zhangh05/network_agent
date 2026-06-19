# agent/runtime/output/models.py
"""Data models for the Result / Artifact / Output Kernel."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class OutputSource:
    source_id: str = ""
    source_type: str = ""  # action_result/tool_result/model_text/user_upload/system
    task_id: str = ""
    step_id: str = ""
    action_id: str = ""
    tool_id: str = ""
    content_type: str = ""  # text/json/table/file/log/image/unknown
    content: Any = None
    summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ArtifactPlan:
    artifact_id: str = ""
    task_id: str = ""
    step_id: str = ""
    source_ids: list[str] = field(default_factory=list)
    kind: str = ""  # markdown/txt/json/csv/docx/pptx/visio/image/log/table/other
    title: str = ""
    filename: str = ""
    target_path: str = ""
    write_mode: str = "create"  # create/update/append/register_only
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ArtifactRecord:
    artifact_id: str = ""
    task_id: str = ""
    step_id: str = ""
    kind: str = ""
    title: str = ""
    path: str = ""
    summary: str = ""
    status: str = "created"  # planned/created/updated/failed/registered
    source_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class OutputSummary:
    task_id: str = ""
    step_id: str = ""
    artifact_ids: list[str] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)
    summary: str = ""
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
