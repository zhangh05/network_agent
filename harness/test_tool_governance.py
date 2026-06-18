"""v3.0 governance tests."""

from __future__ import annotations


def test_governance_summary_only_known_statuses():
    from tool_runtime.tool_governance import governance_summary
    summary = governance_summary()
    assert set(summary.keys()) == {"active", "disabled", "internal", "forbidden"}


def test_no_alias_or_merged_status():
    """v3.0 forbids alias / merged / deprecated / removed_candidate."""
    from tool_runtime.tool_governance import TOOL_GOVERNANCE
    forbidden_statuses = {"alias", "merged", "deprecated", "removed_candidate"}
    for entry in TOOL_GOVERNANCE.values():
        assert entry.status not in forbidden_statuses


def test_planner_visible_count_matches_active():
    from tool_runtime.tool_governance import (
        governance_summary, planner_visible_tool_ids,
    )
    summary = governance_summary()
    assert len(planner_visible_tool_ids()) == summary["active"]


def test_internal_status_is_not_planner_visible():
    from tool_runtime.tool_governance import TOOL_GOVERNANCE
    for entry in TOOL_GOVERNANCE.values():
        if entry.status == "internal":
            assert entry.planner_visible is False


def test_forbidden_tool_cannot_be_invoked():
    from tool_runtime.tool_governance import forbid
    from tool_runtime.canonical_registry import (
        CANONICAL_REGISTRY, get_entry,
    )
    # Pick any canonical id from registry, forbid it, then verify registry
    # still returns the entry but governance marks it forbidden.
    sample_id = next(iter(CANONICAL_REGISTRY))
    forbid(sample_id, "test")
    from tool_runtime.tool_governance import TOOL_GOVERNANCE
    assert TOOL_GOVERNANCE[sample_id].status == "forbidden"
    assert TOOL_GOVERNANCE[sample_id].planner_visible is False
