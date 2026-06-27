# harness/test_tool_module_consolidation.py
"""Verify tool/module consolidation — directory-level tools replace fine-grained tools."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.runtime.capability_routing.manifests import package_by_id
from tool_runtime.tool_governance import get_governance_entry


def test_config_skill_uses_directory_level_tool():
    pkg = package_by_id("config_translation")
    assert pkg is not None
    assert "config.analysis.run" in pkg.tool_ids
    assert ("network" + ".config.translate") not in pkg.tool_ids
    assert len(pkg.tool_ids) <= 3


def test_pcap_skill_uses_directory_level_tool():
    pkg = package_by_id("pcap_analysis")
    assert pkg is not None
    assert "pcap.analysis.run" in pkg.tool_ids
    assert ("network" + ".pcap.parse") not in pkg.tool_ids
    assert len(pkg.tool_ids) <= 2


def test_old_config_tools_are_deleted():
    for tid in ["network" + ".config.parse", "network" + ".config.translate",
                "network" + ".interface.extract", "network" + ".route.extract"]:
        entry = get_governance_entry(tid)
        assert entry.status == "forbidden", f"{tid} should be forbidden (deleted), got {entry.status}"
        assert entry.planner_visible is False


def test_old_pcap_tools_are_deleted():
    for tid in ["network" + ".pcap.parse", "network" + ".pcap.session",
                "network" + ".pcap.filter", "network" + ".pcap.align"]:
        entry = get_governance_entry(tid)
        assert entry.status == "forbidden", f"{tid} should be forbidden (deleted), got {entry.status}"
        assert entry.planner_visible is False


def test_directory_tools_are_planner_visible():
    for tid in ["config.analysis.run", "pcap.analysis.run"]:
        entry = get_governance_entry(tid)
        assert entry.status == "active", f"{tid} should be active, got {entry.status}"
        assert entry.planner_visible is True, f"{tid} should be planner visible"


def test_module_type_classification():
    from agent.runtime.capability_routing.module_types import is_business_module, is_platform_service
    assert is_business_module("config_translation")
    assert is_business_module("config_analysis")
    assert is_business_module("pcap_analysis")
    assert not is_business_module("pcap")
    assert not is_business_module("workspace")
    assert is_platform_service("workspace")
    assert is_platform_service("knowledge")
    assert not is_platform_service("config_translation")
    assert not is_platform_service("config_analysis")
    assert not is_platform_service("pcap_analysis")


def test_capability_module_ids_match_business_modules():
    from agent.runtime.capability_routing.manifests import MODULE_MANIFESTS
    config_pkg = package_by_id("config_translation")
    assert config_pkg is not None
    assert "config_translation" in config_pkg.module_ids
    assert "config_analysis" in config_pkg.module_ids
    assert "workspace" in config_pkg.module_ids
    for mid in config_pkg.module_ids:
        assert mid in MODULE_MANIFESTS, f"{mid} not in MODULE_MANIFESTS"

    pcap_pkg = package_by_id("pcap_analysis")
    assert pcap_pkg is not None
    assert "pcap" in pcap_pkg.module_ids
    assert "workspace" in pcap_pkg.module_ids
    for mid in pcap_pkg.module_ids:
        assert mid in MODULE_MANIFESTS, f"{mid} not in MODULE_MANIFESTS"
