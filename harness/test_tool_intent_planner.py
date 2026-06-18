"""Intent-aware tool routing contracts for LLM tool selection."""

from __future__ import annotations


def _plan(user_input: str, *, safe_context: dict | None = None) -> dict:
    from agent.runtime.tool_category_router import route_tool_scene
    from agent.runtime.tool_planner import plan_tools
    from tool_runtime.tool_namespace import TOOL_NAMESPACE

    rule_scene = route_tool_scene(user_input)
    return plan_tools(
        user_input=user_input,
        safe_context=safe_context or {},
        rule_scene=rule_scene,
        available_catalog={"tools": list(TOOL_NAMESPACE)},
        model_config={"enabled": False},
    )


def test_packet_analysis_routes_to_pcap_tools():
    plan = _plan("分析这个 pcap 报文，看看 TCP 流有没有重传、乱序和 seq gap")

    tools = set(plan["candidate_tools"])
    assert "network.pcap.parse" in tools
    assert "network.pcap.align" in tools
    assert "workspace.file.read" in tools
    assert plan["primary_category"] == "network"
    assert any(
        "报文" in step["goal"] or "PCAP" in step["goal"].upper()
        for step in plan["tool_plan"]
    )


def test_config_translation_prefers_translation_chain_not_parse_chain():
    plan = _plan(
        "把上传的华三配置翻译成思科",
        safe_context={"uploaded_files": [{"path": "files/upload/h3c.txt"}]},
    )

    tools = set(plan["candidate_tools"])
    assert "workspace.file.read" in tools
    assert "network.config.translate" in tools
    assert "network.config.parse" not in tools
    assert plan["tool_plan"][0]["tool_candidates"][0] == "workspace.file.read"


def test_exec_tools_remain_available_for_local_computation_and_diagnostics():
    plan = _plan("用 python 帮我算一下这些接口计数的 95 分位数")

    tools = set(plan["candidate_tools"])
    assert "host.python.exec" in tools or "host.shell.exec" in tools
    assert "network.config.parse" not in tools
    assert plan["primary_category"] == "host"


def test_knowledge_query_does_not_mix_in_config_or_web_tools():
    plan = _plan("查一下知识库里有没有 OSPF 邻居震荡资料")

    tools = set(plan["candidate_tools"])
    assert "knowledge.search" in tools
    assert ("knowledge" + ".query") not in tools
    assert "network.config.parse" not in tools
    # v3.1.0: web.search is a baseline tool, always present
    assert "web.search" in tools
    assert plan["primary_category"] == "knowledge"


def test_runtime_prompt_does_not_forbid_exec_fallback_globally():
    from agent.runtime.prompts import build_system_prompt

    prompt = build_system_prompt(intent="assistant_chat", user_input="用 python 计算一下")

    assert "High-risk tools open an approval popup" in prompt
    assert "Do NOT fall back to host.python.exec" not in prompt
    assert "No fallback to python.exec" not in prompt


def test_pcap_tools_are_registered_in_namespace_and_registry():
    from tool_runtime.canonical_registry import CANONICAL_REGISTRY
    from tool_runtime.tool_namespace import TOOL_NAMESPACE

    for tool_id in ("network.pcap.parse", "network.pcap.session", "network.pcap.filter", "network.pcap.align"):
        assert tool_id in TOOL_NAMESPACE
        assert tool_id in CANONICAL_REGISTRY
