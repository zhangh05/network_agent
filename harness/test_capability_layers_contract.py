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
        "列出当前可用技能": {"skill.manage", "skill.manage"},
        "分析这个华为配置": {"config.manage"},
        "派发子agent搜索BGP邻居建立条件": {"agent.manage", "agent.manage"},
        "查询设备资产清单": {"device.manage", "device.manage"},
        "分析这个pcap抓包": {"pcap.manage"},
    }

    for query, expected in cases.items():
        visible = set(active_tool_catalog(query, limit=24)["tools"])
        missing = sorted(expected - visible)
        assert missing == [], f"{query!r} missing visible tools: {missing}"


def test_core_tool_ids_do_not_expose_exec_for_every_turn():
    from agent.runtime.capability_routing.manifests import CORE_TOOL_IDS

    assert "exec.run" not in CORE_TOOL_IDS
    assert "skill.manage" in CORE_TOOL_IDS
    assert "web.manage" in CORE_TOOL_IDS


def test_network_device_capability_exposes_cmdb_before_exec():
    from agent.runtime.capability_routing.manifests import package_by_id

    package = package_by_id("network_device")
    assert package is not None
    assert "device.manage" in package.tool_ids
    assert "device.manage" in package.tool_ids
    assert "exec.run" in package.tool_ids


def test_hybrid_retriever_filters_weak_semantic_noise():
    from agent.runtime.capability_routing.toolset import active_tool_catalog

    tools = active_tool_catalog("总结一下", limit=24)["tools"]

    assert "agent.manage" not in tools
    assert "skill.manage" in tools


def test_skill_load_remains_visible_as_core_capability_activation():
    from agent.runtime.capability_routing.toolset import active_tool_catalog
    from agent.runtime.tool_planning.planner import deterministic_plan_tools

    catalog = active_tool_catalog("总结一下", limit=24)
    plan = deterministic_plan_tools(
        "总结一下",
        safe_context={},
        rule_scene={"categories": ["report_data"], "groups": {"report_data": ["report"]}},
        available_catalog=catalog,
    )

    assert "skill.manage" in plan["candidate_tools"]
    assert "report.manage" not in plan["candidate_tools"]


def test_planner_filters_destructive_capability_tools_without_explicit_intent():
    from agent.runtime.capability_routing.toolset import active_tool_catalog
    from agent.runtime.tool_planning.planner import deterministic_plan_tools

    catalog = active_tool_catalog("查询设备资产清单", limit=24)
    plan = deterministic_plan_tools(
        "查询设备资产清单",
        safe_context={},
        rule_scene={"categories": ["device"], "groups": {"device": ["asset"]}},
        available_catalog=catalog,
    )

    # v3.9.2: device.manage is the merged tool. The "查询" query is a read
    # intent so the read-class sub-action (list/get) is allowed. The merge
    # makes the destructive gate coarser: device.manage has destructive=True
    # in its manifest, so the visibility layer requires explicit destructive
    # intent (allowed_actions) to surface it.
    candidates = set(plan["candidate_tools"])
    # device.manage is removed because no explicit destructive intent
    # (query is a read), but the merged tool still gates add/delete unless
    # the user said "add" / "delete" / "修改".
    assert "device.manage" not in candidates


def test_planner_allows_device_add_only_for_explicit_mutation_intent():
    from agent.runtime.capability_routing.toolset import active_tool_catalog
    from agent.runtime.cognition.scene_decision import decide_scene
    from agent.runtime.tool_planning.planner import deterministic_plan_tools
    from agent.runtime.tool_planning.scene_adapter import scene_to_rule_scene

    query = "添加设备，IP 是 10.0.0.1"
    catalog = active_tool_catalog(query, limit=24)
    rule_scene = scene_to_rule_scene(decide_scene(query))
    plan = deterministic_plan_tools(query, safe_context={}, rule_scene=rule_scene, available_catalog=catalog)

    assert "device.manage" in plan["candidate_tools"]
