"""v3.0 canonical tool architecture tests."""

from __future__ import annotations


def test_canonical_namespace_has_tools():
    from tool_runtime.tool_namespace import TOOL_NAMESPACE
    assert len(TOOL_NAMESPACE) > 0
    for canonical_id in TOOL_NAMESPACE:
        assert "." in canonical_id


def test_governance_has_only_valid_statuses():
    from tool_runtime.tool_governance import TOOL_GOVERNANCE, VALID_STATUSES
    assert set(VALID_STATUSES) == {"active", "disabled", "internal", "forbidden"}
    for entry in TOOL_GOVERNANCE.values():
        assert entry.status in VALID_STATUSES


def test_canonical_registry_keys_are_canonical():
    from tool_runtime.tool_namespace import TOOL_NAMESPACE
    from tool_runtime.canonical_registry import CANONICAL_REGISTRY
    for canonical_id in CANONICAL_REGISTRY:
        assert canonical_id in TOOL_NAMESPACE


def test_handler_ids_are_internal():
    """handler_id is internal-only metadata. It is allowed to equal
    canonical_tool_id when there is no namespace aliasing, but it must
    always be present and must never be exposed through the public
    catalog / API surface."""
    from tool_runtime.canonical_registry import CANONICAL_REGISTRY
    for entry in CANONICAL_REGISTRY.values():
        assert entry.handler_id
    # Verify handler_id is not part of the public catalog surface.
    import json
    from tool_runtime.tool_namespace import metadata_for_tool
    for canonical_id in CANONICAL_REGISTRY:
        meta = metadata_for_tool(canonical_id)
        # The namespace metadata() must NOT include handler_id.
        assert "handler_id" not in meta


def test_planner_visible_only_when_active():
    from tool_runtime.tool_governance import TOOL_GOVERNANCE
    for entry in TOOL_GOVERNANCE.values():
        if entry.status == "active":
            assert entry.planner_visible is True
        else:
            assert entry.planner_visible is False


def test_no_legacy_aliases_in_public_surface():
    """Public surface must not expose transition / migration fields."""
    from tool_runtime.tool_namespace import TOOL_NAMESPACE
    for entry in TOOL_NAMESPACE.values():
        meta = entry.metadata()
        # These keys must NOT appear in public namespace metadata.
        for forbidden in ("execution_tool_id", "legacy_tool_ids",
                          "replacement", "migration_notes"):
            assert forbidden not in meta


def test_capability_actions_resolve_to_canonical():
    from tool_runtime.tool_namespace import TOOL_NAMESPACE
    from tool_runtime.capability_actions import CAPABILITY_ACTIONS
    for action in CAPABILITY_ACTIONS.values():
        for tool_id in action.preferred_tools + action.fallback_tools:
            assert tool_id in TOOL_NAMESPACE
