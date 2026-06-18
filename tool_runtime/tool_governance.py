"""v3.0 canonical-only tool governance.

Public identity contract:

  - status is one of: active | disabled | internal | forbidden.
  - planner_visible is True only for status == 'active'.
  - reason is a free-form human-readable note.
  - Tools that need to be retired are marked 'forbidden'.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from tool_runtime.tool_namespace import TOOL_NAMESPACE


VALID_STATUSES = ("active", "disabled", "internal", "forbidden")


@dataclass(frozen=True)
class ToolGovernanceEntry:
    canonical_tool_id: str
    status: str
    reason: str
    planner_visible: bool

    def __post_init__(self) -> None:
        if self.status not in VALID_STATUSES:
            raise ValueError(
                f"invalid governance status: {self.status} "
                f"(must be one of {VALID_STATUSES})"
            )


# ----------------------------------------------------------------------
# v3.0 governance baseline.
#
# Default rule: a canonical_tool_id is 'active' and planner_visible
# unless explicitly listed below. Only deviations from the default
# are recorded here. The TOOL_GOVERNANCE dict is built lazily from
# namespace + overrides so any canonical_id in TOOL_NAMESPACE gets a
# valid governance entry.
# ----------------------------------------------------------------------

_OVERRIDES: dict[str, tuple[str, str]] = {
    # Disabled / internal tools are explicitly enumerated; everything
    # else is 'active' by default.
    # 'web.news.search': ('disabled', "Not selected by planner; use only on explicit request."),
}


def _build_governance() -> dict[str, ToolGovernanceEntry]:
    entries: dict[str, ToolGovernanceEntry] = {}
    for canonical_id in TOOL_NAMESPACE:
        status, reason = _OVERRIDES.get(canonical_id, ("active", "default active canonical tool."))
        planner_visible = status == "active"
        entries[canonical_id] = ToolGovernanceEntry(
            canonical_tool_id=canonical_id,
            status=status,
            reason=reason,
            planner_visible=planner_visible,
        )
    return entries


TOOL_GOVERNANCE: dict[str, ToolGovernanceEntry] = _build_governance()


def get_governance_entry(canonical_tool_id: str) -> ToolGovernanceEntry:
    """Return the governance entry for a canonical tool id.

    Returns a synthetic 'forbidden' entry when the id is unknown.
    """
    return TOOL_GOVERNANCE.get(
        canonical_tool_id,
        ToolGovernanceEntry(
            canonical_tool_id=canonical_tool_id,
            status="forbidden",
            reason="unknown canonical_tool_id",
            planner_visible=False,
        ),
    )


def governance_metadata(canonical_tool_id: str) -> dict[str, Any]:
    entry = TOOL_GOVERNANCE.get(canonical_tool_id)
    if entry is None:
        return {
            "governance_status": "forbidden",
            "governance_reason": "unknown canonical_tool_id",
            "planner_visible": False,
        }
    return {
        "governance_status": entry.status,
        "governance_reason": entry.reason,
        "planner_visible": entry.planner_visible,
    }


def governance_summary() -> dict[str, int]:
    counts = {status: 0 for status in VALID_STATUSES}
    for entry in TOOL_GOVERNANCE.values():
        counts[entry.status] = counts.get(entry.status, 0) + 1
    return counts


def planner_visible_tool_ids() -> list[str]:
    return sorted(
        cid for cid, entry in TOOL_GOVERNANCE.items()
        if entry.planner_visible
    )


def is_planner_visible(canonical_tool_id: str) -> bool:
    entry = TOOL_GOVERNANCE.get(canonical_tool_id)
    return bool(entry and entry.planner_visible)


def forbid(canonical_tool_id: str, reason: str) -> None:
    """Runtime API to mark a tool as forbidden (used by policy overrides)."""
    TOOL_GOVERNANCE[canonical_tool_id] = ToolGovernanceEntry(
        canonical_tool_id=canonical_tool_id,
        status="forbidden",
        reason=reason,
        planner_visible=False,
    )


@dataclass(frozen=True)
class ResolvedGovernance:
    """Resolution of a canonical_tool_id to its handler.

    v3.0: this is an internal type. Public surfaces (LLM prompts,
    API responses, frontend state) must use canonical_tool_id only.
    handler_id is kept for the registry dispatch path; canonical_tool_id
    and handler_id are the same string for every registered tool.
    """
    canonical_tool_id: str
    handler_id: str
    governance_status: str
    warning: str = ""


def resolve_governed_tool_id(requested_tool_id: str) -> ResolvedGovernance:
    """Resolve a canonical ID to a (canonical_id, handler_id, status).

    v3.0 has no alias layer. The canonical_tool_id and handler_id are
    looked up directly; status is the governance entry's status.
    Unknown IDs return a synthetic ResolvedGovernance with the input as
    both canonical and handler id (used by router test shims).
    """
    if requested_tool_id in TOOL_NAMESPACE:
        entry = TOOL_GOVERNANCE[requested_tool_id]
        return ResolvedGovernance(
            canonical_tool_id=requested_tool_id,
            handler_id=getattr(
                TOOL_NAMESPACE[requested_tool_id], "handler_id",
                requested_tool_id,
            ),
            governance_status=entry.status,
        )
    return ResolvedGovernance(
        canonical_tool_id=requested_tool_id,
        handler_id=requested_tool_id,
        governance_status="unknown",
    )
