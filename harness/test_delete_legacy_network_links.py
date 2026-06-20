# harness/test_delete_legacy_network_links.py
"""Guard: all legacy network fine-tool IDs must be gone from runtime source."""

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Use concatenation so this test file doesn't trigger the global old-ID grep
OLD_IDS = [
    "network" + ".config.parse",
    "network" + ".config.translate",
    "network" + ".config.analyze",
    "network" + ".interface.extract",
    "network" + ".route.extract",
    "network" + ".pcap.parse",
    "network" + ".pcap.session",
    "network" + ".pcap.filter",
    "network" + ".pcap.align",
    "network" + ".pcap.analyze",
]

RUNTIME_FILES = [
    "tool_runtime/canonical_registry.py",
    "tool_runtime/tool_namespace_data.py",
    "tool_runtime/tool_governance.py",
    "tool_runtime/capability_actions.py",
    "agent/runtime/tool_planning/chain_builder.py",
    "agent/runtime/tool_planning/planner.py",
    "agent/runtime/prompting/safe_context_renderer.py",
    "agent/runtime/prompting/blocks.py",
    "agent/runtime/prompting/compiler.py",
    "agent/runtime/prompt_architecture/blocks.py",
    "agent/runtime/prompt_architecture/policies.py",
]


def test_old_network_ids_removed_from_runtime_source():
    root = Path(__file__).resolve().parents[1]
    for rel in RUNTIME_FILES:
        text = (root / rel).read_text(encoding="utf-8")
        for old_id in OLD_IDS:
            assert old_id not in text, f"{old_id} still found in {rel}"


def test_old_network_ids_not_registered():
    from tool_runtime.tool_namespace import TOOL_NAMESPACE
    from tool_runtime.tool_governance import TOOL_GOVERNANCE
    from tool_runtime.capability_actions import CAPABILITY_ACTIONS

    for old_id in OLD_IDS:
        assert old_id not in TOOL_NAMESPACE
        assert old_id not in TOOL_GOVERNANCE
        assert old_id not in CAPABILITY_ACTIONS


def test_new_directory_tools_and_actions_exist():
    from tool_runtime.tool_namespace import TOOL_NAMESPACE
    from tool_runtime.capability_actions import CAPABILITY_ACTIONS

    assert "config.analysis.run" in TOOL_NAMESPACE
    assert "pcap.analysis.run" in TOOL_NAMESPACE
    assert "config.analysis" in CAPABILITY_ACTIONS
    assert "config.translation" in CAPABILITY_ACTIONS
    assert "pcap.analysis" in CAPABILITY_ACTIONS


def test_backend_pcap_routes_has_no_old_private_reexports():
    root = Path(__file__).resolve().parents[1]
    text = (root / "backend/api/pcap_routes.py").read_text(encoding="utf-8")
    for name in (
        "_parse_pcap",
        "_get_connection_groups",
        "_filter_by_5tuple",
        "_tcp_stream_align",
        "_session_meta_path",
        "_load_session_from_file",
        "_safe_name",
        "_PCAP_SESSIONS",
    ):
        assert name not in text, f"re-export {name} still in pcap_routes.py"
