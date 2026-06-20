# harness/test_capability_routing_refactor.py
"""Acceptance checks for capability-first routing."""

from agent.runtime.capability_routing import build_active_tool_bundle, route_capabilities
from agent.runtime.capability_routing.manifests import CAPABILITY_PACKAGES, CORE_TOOL_IDS, MODULE_MANIFESTS


def test_capability_manifests_define_business_boundary():
    assert CAPABILITY_PACKAGES
    ids = {pkg.capability_id for pkg in CAPABILITY_PACKAGES}
    assert {"workspace_read", "knowledge_qa", "config_translation", "pcap_analysis"} <= ids
    for pkg in CAPABILITY_PACKAGES:
        assert pkg.module_ids
        assert pkg.tool_ids
        assert len(pkg.tool_ids) <= 6
        for module_id in pkg.module_ids:
            assert module_id in MODULE_MANIFESTS


def test_default_visible_tool_set_is_small():
    bundle = build_active_tool_bundle("hello")
    assert bundle.visible_tools
    assert len(bundle.visible_tools) <= 12
    assert set(CORE_TOOL_IDS) & set(bundle.visible_tools)
    assert "workspace.file.read" in bundle.visible_tools


def test_config_request_routes_to_config_capability():
    route = route_capabilities("帮我翻译 H3C 到 Cisco 的配置")
    assert "config_translation" in route.capability_ids
    bundle = build_active_tool_bundle("帮我翻译 H3C 到 Cisco 的配置")
    assert "config.analysis.run" in bundle.visible_tools
    assert len(bundle.visible_tools) <= 12


def test_pcap_request_routes_to_pcap_capability():
    route = route_capabilities("分析这个 pcap 抓包里的 tcp 重传")
    assert "pcap_analysis" in route.capability_ids
    bundle = build_active_tool_bundle("分析这个 pcap 抓包里的 tcp 重传")
    assert "pcap.analysis.run" in bundle.visible_tools
    assert len(bundle.visible_tools) <= 12
