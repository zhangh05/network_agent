"""Contract tests for the tool / skill / module capability layers."""

import importlib


def test_capability_package_tool_refs_are_registered_and_manifested():
    from agent.runtime.capability_routing.manifests import CAPABILITY_PACKAGES, CORE_TOOL_IDS
    from tool_runtime.canonical_registry import CANONICAL_REGISTRY
    from tool_runtime.manifest_registry import MANIFESTS

    refs = set(CORE_TOOL_IDS)
    for package in CAPABILITY_PACKAGES:
        refs.update(package.tool_ids)

    missing_registry = sorted(tid for tid in refs if tid not in CANONICAL_REGISTRY)
    missing_manifest = sorted(tid for tid in refs if tid not in MANIFESTS)

    assert missing_registry == []
    assert missing_manifest == []


def test_module_service_manifests_are_importable():
    from agent.runtime.capability_routing.manifests import MODULE_MANIFESTS

    failures = []
    for module_id, manifest in sorted(MODULE_MANIFESTS.items()):
        try:
            importlib.import_module(manifest.service_path)
        except Exception as exc:  # pragma: no cover - assertion carries details
            failures.append((module_id, manifest.service_path, type(exc).__name__, str(exc)[:120]))

    assert failures == []


def test_active_tool_catalog_exposes_skill_and_routed_capability_tools():
    from agent.runtime.capability_routing.toolset import active_tool_catalog

    cases = {
        "列出当前可用技能": {"skill.list", "skill.load"},
        "分析这个华为配置": {"config.analysis.run"},
        "派发子agent搜索BGP邻居建立条件": {"agent.spawn", "agent.result.get"},
        "查询设备资产清单": {"device.list", "device.get"},
        "分析这个pcap抓包": {"pcap.analysis.run"},
    }

    for query, expected in cases.items():
        visible = set(active_tool_catalog(query, limit=24)["tools"])
        missing = sorted(expected - visible)
        assert missing == [], f"{query!r} missing visible tools: {missing}"
