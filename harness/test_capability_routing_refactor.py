# harness/test_capability_routing_refactor.py
"""Acceptance checks for capability-first routing."""

from types import SimpleNamespace

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


def test_ascii_keywords_use_token_boundaries_instead_of_substrings():
    route = route_capabilities("check profile health")
    assert "runtime_diagnostics" in route.capability_ids
    assert "workspace_read" not in route.capability_ids


def test_ambiguous_request_uses_active_artifact_context():
    route = route_capabilities(
        "帮我看看这个有没有问题",
        safe_context={"artifact_refs": [{"artifact_id": "art_1"}]},
    )
    assert route.capability_ids[0] == "workspace_read"
    assert route.fallback_used is False
    assert route.ambiguous is False
    assert "context:artifact_refs" in route.signals


def test_continuation_scene_routes_to_memory_without_memory_keyword():
    scene = SimpleNamespace(
        category="assistant_chat",
        reason="follow_up",
        needs_memory=True,
        is_memory_task=True,
    )
    route = route_capabilities("继续上次那个", scene=scene)
    assert "memory_lookup" in route.capability_ids
    assert "scene:memory" in route.signals


def test_route_exposes_machine_readable_diagnostics():
    route = route_capabilities("分析这个 pcap 抓包")
    payload = route.to_dict()
    assert payload["route_version"]
    assert payload["capability_ids"] == list(route.capability_ids)
    assert payload["candidate_scores"]["pcap_analysis"] > 0
    assert payload["latency_ms"] >= 0


def test_bundle_reports_truncation_and_routing_diagnostics():
    bundle = build_active_tool_bundle(
        "分析这个 pcap 抓包里的 tcp 重传并整理报告",
        limit=7,
    )
    assert len(bundle.visible_tools) <= 7
    assert bundle.metadata["visible_tool_count"] == len(bundle.visible_tools)
    assert bundle.metadata["route"]["route_version"]
    assert bundle.metadata["truncated"] is True
