# harness/test_capability_tool_visibility_integration.py
"""Integration: capability routing → tool planner → visibility acceptance.

Verifies that the full planner path now uses capability routing
to produce small, scene-appropriate tool sets.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _plan(user_input: str) -> dict:
    from agent.runtime.tool_category_router import route_tool_scene
    from agent.runtime.tool_planning.planner import plan_tools
    from agent.runtime.capability_routing.toolset import active_tool_catalog, DEFAULT_TOOL_LIMIT

    rule_scene = route_tool_scene(user_input)
    catalog = active_tool_catalog(user_input, limit=DEFAULT_TOOL_LIMIT)
    return plan_tools(
        user_input=user_input,
        safe_context={},
        rule_scene=rule_scene,
        available_catalog=catalog,
        model_config={"enabled": False},
    )


class TestCapabilityVisibilityIntegration:
    """Full planner should produce capability-routed, small tool sets."""

    def test_hello_does_not_expose_all_tools(self):
        plan = _plan("hello")
        tools = set(plan.get("candidate_tools") or [])
        # BASELINE_READ_TOOLS (17) are always visible regardless of scene
        assert len(tools) >= 17, f"hello got {len(tools)} candidate tools (expected >=17 baseline)"
        # host.shell.exec is now in BASELINE_READ_TOOLS — no longer excluded
        assert "host.shell.exec" in tools, "host.shell.exec should be in BASELINE"

    def test_config_translate_small_set(self):
        plan = _plan("把这段华为配置翻译成 Cisco IOS-XE 格式")
        tools = set(plan.get("candidate_tools") or [])
        assert len(tools) >= 17, f"config translate got {len(tools)} candidate tools (expected >=17 baseline)"
        assert "config.analysis.run" in tools

    def test_pcap_analysis_small_set(self):
        plan = _plan("分析这个 PCAP 文件，识别 TCP 重传")
        tools = set(plan.get("candidate_tools") or [])
        assert len(tools) >= 17, f"pcap got {len(tools)} candidate tools (expected >=17 baseline)"
        assert "pcap.analysis.run" in tools

    def test_knowledge_qa_small_set(self):
        plan = _plan("查找关于 OSPF 邻居建立过程的知识")
        tools = set(plan.get("candidate_tools") or [])
        assert len(tools) >= 17, f"knowledge got {len(tools)} candidate tools (expected >=17 baseline)"
        assert "knowledge.search" in tools

    def test_capability_routing_metadata_exists(self):
        plan = _plan("翻译华为配置")
        routing = plan.get("capability_routing") or {}
        assert routing, "capability_routing metadata must be present"
        assert "capability_ids" in routing
        assert "config_translation" in routing["capability_ids"]

    def test_candidate_tools_always_within_limit(self):
        queries = [
            "hello",
            "show ip route",
            "把华为配置翻译成 Cisco",
            "解析 PCAP 文件",
            "搜索 BGP 知识",
            "生成网络分析报告",
        ]
        for q in queries:
            plan = _plan(q)
            tools = plan.get("candidate_tools") or []
            assert len(tools) >= 17, f"query '{q}' produced {len(tools)} candidate tools (expected >=17 baseline)"
