"""v3.9.4 hard cut — API surface invariants.

The backend must not leak any pre-v3.9.2 tool name to the frontend
or to LLM prompts. The legacy ids must be absent from:
  - /api/skills (skill list response)
  - /api/capabilities (module list response)
  - the LLM tool catalog compiled from the ToolRegistry
"""

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Use a stable temp directory for workspace state.
os.environ.setdefault("WORKSPACE_ROOT", "/tmp/network_agent_v394_test")

from tool_runtime.tool_namespace import TOOL_NAMESPACE


LEGACY_TOOL_IDS = {
    "device.list", "device.get", "device.add", "device.delete",
    "git.status", "git.diff", "git.log", "git.commit", "git.push",
    "browser.navigate", "browser.extract", "browser.screenshot", "browser.click",
    "knowledge.search", "pcap.analysis.run",
    "system.review.item.list", "system.review.item.update",
    "system.review.summary.get", "system.review.finding.list",
}


def _all_tool_ids_in_response(payload) -> set[str]:
    """Recursively collect every string that *looks* like a tool id
    in a JSON payload. A tool id is any string of the form
    "<namespace>.<verb>[.<scope>]" that contains a dot."""
    found = set()
    if isinstance(payload, dict):
        for k, v in payload.items():
            if isinstance(v, str) and "." in v and k.endswith("_id") is False:
                # Only treat as a tool id if it matches TOOL_NAMESPACE
                # OR is in our legacy set; we test both for absence.
                if v in TOOL_NAMESPACE or v in LEGACY_TOOL_IDS:
                    found.add(v)
            found |= _all_tool_ids_in_response(v)
    elif isinstance(payload, list):
        for item in payload:
            found |= _all_tool_ids_in_response(item)
    return found


def test_legacy_tool_ids_absent_from_tooL_namespace():
    """Hard invariant: legacy ids must not be in TOOL_NAMESPACE."""
    assert LEGACY_TOOL_IDS.isdisjoint(set(TOOL_NAMESPACE)), (
        f"legacy ids leaked into TOOL_NAMESPACE: "
        f"{LEGACY_TOOL_IDS & set(TOOL_NAMESPACE)}"
    )


def test_canonical_namespace_has_exactly_21_tools():
    """v3.9.2 design: 21 canonical tools, no more, no less."""
    assert len(TOOL_NAMESPACE) == 21, (
        f"expected 21 canonical tools, got {len(TOOL_NAMESPACE)}: "
        f"{sorted(TOOL_NAMESPACE)}"
    )


def test_all_canonical_tools_have_manifests():
    from tool_runtime.manifest_registry import MANIFESTS
    missing = set(TOOL_NAMESPACE) - set(MANIFESTS.keys())
    assert not missing, f"tools without manifests: {missing}"


def test_canonical_registry_lists_all_21():
    from tool_runtime.canonical_registry import CANONICAL_REGISTRY
    assert len(CANONICAL_REGISTRY) == 21
    assert set(CANONICAL_REGISTRY.keys()) == set(TOOL_NAMESPACE)


def test_default_runtime_services_exposes_21_tools():
    from agent.runtime.services import default_runtime_services
    services = default_runtime_services()
    registry = services.tool_service.registry
    tool_ids = {t.tool_id for t in registry.list_all()}
    assert tool_ids == set(TOOL_NAMESPACE), (
        f"registry mismatch: missing {set(TOOL_NAMESPACE) - tool_ids}, "
        f"extra {tool_ids - set(TOOL_NAMESPACE)}"
    )


def test_default_runtime_services_capability_catalog_is_picklable():
    """State deepcopy must work — capability_catalog must be plain data."""
    import copy
    from agent.runtime.services import default_runtime_services
    services = default_runtime_services()
    cat = services.capability_catalog
    assert isinstance(cat, list)
    # Should be deepcopy-able without raising.
    snap = copy.deepcopy(cat)
    assert snap == cat


def test_no_register_capability_tools_method():
    """ToolRegistry must not expose the legacy register_capability_tools
    path. v3.9.4: tools come only from ToolRuntimeClient."""
    from agent.tools.registry import ToolRegistry
    assert not hasattr(ToolRegistry, "register_capability_tools") or \
        getattr(ToolRegistry, "register_capability_tools", None) is None, (
        "ToolRegistry.register_capability_tools must be removed in v3.9.4"
    )


def test_legacy_tool_ids_absent_from_skill_manage_handlers():
    """skill.manage handlers must not surface legacy tool ids."""
    from tool_runtime.general_tools.skill_tools import (
        handle_skill_list, handle_skill_find,
    )
    from tool_runtime.schemas import ToolInvocation
    inv = ToolInvocation(tool_id="skill.manage", arguments={}, workspace_id="default")
    out = handle_skill_list(inv)
    results = out.get("results", []) if isinstance(out, dict) else []
    found = set()
    for r in results:
        for tid in r.get("tool_ids", []) or []:
            found.add(tid)
    assert found.isdisjoint(LEGACY_TOOL_IDS), (
        f"skill.list returned legacy tool ids: {found & LEGACY_TOOL_IDS}"
    )

    out2 = handle_skill_find(inv)
    inv2 = ToolInvocation(tool_id="skill.manage",
                          arguments={"query": "all"},
                          workspace_id="default")
    out2 = handle_skill_find(inv2)
    results2 = out2.get("results", []) if isinstance(out2, dict) else []
    found2 = set()
    for r in results2:
        for tid in r.get("tool_ids", []) or []:
            found2.add(tid)
    assert found2.isdisjoint(LEGACY_TOOL_IDS)


def test_legacy_tool_ids_absent_from_catalog_recommended():
    """Catalog must not recommend any legacy tool id."""
    from agent.capabilities import catalog as _catalog
    bad = set()
    for cap in _catalog.list_all():
        for tid in cap.get("recommended_tool_ids", ()):
            if tid in LEGACY_TOOL_IDS:
                bad.add(tid)
    assert not bad, f"catalog recommends legacy tool ids: {bad}"
