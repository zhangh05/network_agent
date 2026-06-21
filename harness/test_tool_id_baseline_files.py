"""harness/test_tool_id_baseline_files.py

v3.0: Replace the v2.x baseline-file existence check with a v3.0
canonical-only registry / namespace parity check. There are no
baselines/*.txt files any more (deleted in v3.0); the parity check
moved into ``compare_tool_id_baseline.py``.
"""

from __future__ import annotations


def test_canonical_registry_matches_namespace():
    from tool_runtime.tool_namespace import TOOL_NAMESPACE
    from tool_runtime.canonical_registry import CANONICAL_REGISTRY
    ns = set(TOOL_NAMESPACE)
    cr = set(CANONICAL_REGISTRY)
    assert ns == cr, (
        f"Registry / namespace mismatch:\n"
        f"  canonical (no handler): {sorted(ns - cr)}\n"
        f"  handler (no canonical): {sorted(cr - ns)}"
    )


def test_governance_has_only_canonical_ids():
    from tool_runtime.tool_namespace import TOOL_NAMESPACE
    from tool_runtime.tool_governance import TOOL_GOVERNANCE
    assert set(TOOL_GOVERNANCE) == set(TOOL_NAMESPACE)


def test_capability_actions_resolve_only_to_canonical():
    from tool_runtime.tool_namespace import TOOL_NAMESPACE
    from tool_runtime.capability_actions import CAPABILITY_ACTIONS
    canonical = set(TOOL_NAMESPACE)
    for action in CAPABILITY_ACTIONS.values():
        for tool_id in action.preferred_tools + action.fallback_tools:
            assert tool_id in canonical, (
                f"capability_action {action.capability_action} "
                f"references unknown canonical id {tool_id}"
            )


def test_baseline_directory_uses_current_format():
    from pathlib import Path
    ROOT = Path(__file__).resolve().parents[1]
    baselines_dir = ROOT / "baselines"
    assert baselines_dir.exists()
    leftover = list(baselines_dir.glob("*.txt")) + list(baselines_dir.glob("*.json"))
    assert not leftover, f"baselines directory should not contain raw snapshots: {leftover}"
