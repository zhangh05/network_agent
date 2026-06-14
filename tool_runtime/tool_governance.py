"""v2.3 tool governance metadata and governed resolution.

The governance layer does not remove execution tools. It classifies canonical
tools so planners and catalogs can prefer stable capability actions while old
execution ids and trace ids remain explainable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tool_runtime.tool_namespace import TOOL_NAMESPACE, get_canonical_tool_id, get_execution_tool_id


GOVERNANCE_STATUSES = {"keep", "alias", "merged", "deprecated", "removed_candidate"}
PLANNER_VISIBLE_STATUSES = {"keep"}


@dataclass(frozen=True)
class ToolGovernanceEntry:
    canonical_tool_id: str
    status: str
    replacement: str | None
    deprecate_after: str | None
    reason: str
    overlap_group: str
    migration_notes: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "canonical_tool_id": self.canonical_tool_id,
            "status": self.status,
            "replacement": self.replacement,
            "deprecate_after": self.deprecate_after,
            "reason": self.reason,
            "overlap_group": self.overlap_group,
            "migration_notes": self.migration_notes,
        }


@dataclass(frozen=True)
class GovernedToolResolution:
    requested_tool_id: str
    canonical_tool_id: str
    effective_canonical_tool_id: str
    execution_tool_id: str
    governance_status: str
    replacement: str | None
    warning: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "requested_tool_id": self.requested_tool_id,
            "canonical_tool_id": self.canonical_tool_id,
            "effective_canonical_tool_id": self.effective_canonical_tool_id,
            "execution_tool_id": self.execution_tool_id,
            "governance_status": self.governance_status,
            "replacement": self.replacement,
            "warning": self.warning,
        }


def _overlap_group(canonical_tool_id: str) -> str:
    if canonical_tool_id.startswith("workspace.file."):
        return "workspace_file"
    if canonical_tool_id.startswith("workspace.artifact.read"):
        return "artifact_read"
    if canonical_tool_id.startswith("workspace.artifact."):
        return "artifact"
    if canonical_tool_id.startswith("knowledge.search"):
        return "knowledge_search"
    if canonical_tool_id.startswith("knowledge.chunk."):
        return "knowledge_chunk"
    if canonical_tool_id.startswith("knowledge.source."):
        return "knowledge_source"
    if canonical_tool_id.startswith(("report.", "data.", "text.", "document.", "diagram.")):
        return "report_data"
    if canonical_tool_id.startswith("web."):
        return "web_misc"
    if canonical_tool_id.startswith("host."):
        return "host_execution"
    return canonical_tool_id.split(".", 1)[0]


def _governance_for(canonical_tool_id: str) -> ToolGovernanceEntry:
    merged: dict[str, tuple[str, str]] = {
        "workspace.file.list_all": (
            "workspace.file.list",
            "workspace.list_files is a broader listing variant; keep compatibility but plan against workspace.file.list.",
        ),
    }
    alias: dict[str, tuple[str, str]] = {
        "workspace.file.path_exists": (
            "workspace.file.exists",
            "workspace.path_exists is a compatibility alias for workspace.file.exists.",
        ),
        "workspace.artifact.read_safe": (
            "workspace.artifact.read",
            "Safe-read semantics are represented by policy and metadata; use workspace.artifact.read as the stable action.",
        ),
    }
    deprecated: dict[str, str] = {
        "web.news.search": "News search remains callable for legacy requests but is not a default planner action.",
    }
    removed_candidate: dict[str, tuple[str | None, str]] = {
        "text.classify": (
            None,
            "Rule-only text classification is a future candidate for consolidation into text.process.",
        ),
    }

    if canonical_tool_id in merged:
        replacement, reason = merged[canonical_tool_id]
        return ToolGovernanceEntry(
            canonical_tool_id=canonical_tool_id,
            status="merged",
            replacement=replacement,
            deprecate_after=None,
            reason=reason,
            overlap_group=_overlap_group(canonical_tool_id),
            migration_notes=f"Use {replacement}; legacy execution remains registered for trace compatibility.",
        )
    if canonical_tool_id in alias and alias[canonical_tool_id][0] in TOOL_NAMESPACE:
        replacement, reason = alias[canonical_tool_id]
        return ToolGovernanceEntry(
            canonical_tool_id=canonical_tool_id,
            status="alias",
            replacement=replacement,
            deprecate_after=None,
            reason=reason,
            overlap_group=_overlap_group(canonical_tool_id),
            migration_notes=f"Resolve planner calls to {replacement}; keep old id as alias only.",
        )
    if canonical_tool_id in deprecated:
        return ToolGovernanceEntry(
            canonical_tool_id=canonical_tool_id,
            status="deprecated",
            replacement=None,
            deprecate_after="v2.4-review",
            reason=deprecated[canonical_tool_id],
            overlap_group=_overlap_group(canonical_tool_id),
            migration_notes="Do not select in planner; legacy direct calls still execute with a warning.",
        )
    if canonical_tool_id in removed_candidate:
        replacement, reason = removed_candidate[canonical_tool_id]
        return ToolGovernanceEntry(
            canonical_tool_id=canonical_tool_id,
            status="removed_candidate",
            replacement=replacement,
            deprecate_after="next-major",
            reason=reason,
            overlap_group=_overlap_group(canonical_tool_id),
            migration_notes="Keep in v2.3; require a deprecation release before any real removal.",
        )
    return ToolGovernanceEntry(
        canonical_tool_id=canonical_tool_id,
        status="keep",
        replacement=None,
        deprecate_after=None,
        reason="Stable canonical capability; keep visible to planner when selected by capability action.",
        overlap_group=_overlap_group(canonical_tool_id),
        migration_notes="No migration required.",
    )


TOOL_GOVERNANCE: dict[str, ToolGovernanceEntry] = {
    canonical_id: _governance_for(canonical_id)
    for canonical_id in TOOL_NAMESPACE
}


def get_governance_entry(tool_id: str) -> ToolGovernanceEntry:
    canonical = get_canonical_tool_id(tool_id)
    return TOOL_GOVERNANCE.get(canonical, _governance_for(canonical))


def is_planner_visible(tool_id: str) -> bool:
    entry = get_governance_entry(tool_id)
    return entry.status in PLANNER_VISIBLE_STATUSES


def planner_visible_tool_ids() -> list[str]:
    return sorted(
        canonical_id
        for canonical_id, entry in TOOL_GOVERNANCE.items()
        if entry.status in PLANNER_VISIBLE_STATUSES
    )


def governance_summary() -> dict[str, int]:
    summary = {status: 0 for status in GOVERNANCE_STATUSES}
    for entry in TOOL_GOVERNANCE.values():
        summary[entry.status] += 1
    return summary


def governance_metadata(tool_id: str) -> dict[str, Any]:
    entry = get_governance_entry(tool_id)
    return {
        "governance_status": entry.status,
        "replacement": entry.replacement,
        "deprecate_after": entry.deprecate_after,
        "overlap_group": entry.overlap_group,
        "planner_visible": is_planner_visible(tool_id),
        "migration_notes": entry.migration_notes,
        "governance_reason": entry.reason,
    }


def resolve_governed_tool_id(tool_id: str) -> GovernedToolResolution:
    canonical = get_canonical_tool_id(tool_id)
    entry = get_governance_entry(canonical)
    effective = canonical
    warning = ""
    if entry.status in {"alias", "merged"} and entry.replacement:
        effective = entry.replacement
        warning = f"{canonical} is {entry.status}; resolved to {entry.replacement}"
    elif entry.status in {"deprecated", "removed_candidate"}:
        warning = f"{canonical} is {entry.status}; keep for compatibility only"
    return GovernedToolResolution(
        requested_tool_id=tool_id,
        canonical_tool_id=canonical,
        effective_canonical_tool_id=effective,
        execution_tool_id=get_execution_tool_id(effective),
        governance_status=entry.status,
        replacement=entry.replacement,
        warning=warning,
    )
