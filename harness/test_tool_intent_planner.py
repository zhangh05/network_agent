"""Intent-aware tool routing contracts for LLM tool selection."""

from __future__ import annotations


def _plan(user_input: str, *, safe_context: dict | None = None) -> dict:
    from agent.runtime.tool_category_router import route_tool_scene
    from agent.runtime.tool_planning.planner import plan_tools
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
    from agent.runtime.prompting.profile import PromptProfile

    prompt = PromptProfile.from_classify_intent(intent="assistant_chat", user_input="用 python 计算一下").build()

    assert "High-risk tools open an approval popup" in prompt
    assert "Do NOT fall back to host.python.exec" not in prompt
    assert "No fallback to python.exec" not in prompt


def test_pcap_tools_are_registered_in_namespace_and_registry():
    from tool_runtime.canonical_registry import CANONICAL_REGISTRY
    from tool_runtime.tool_namespace import TOOL_NAMESPACE

    for tool_id in ("network.pcap.parse", "network.pcap.session", "network.pcap.filter", "network.pcap.align"):
        assert tool_id in TOOL_NAMESPACE
        assert tool_id in CANONICAL_REGISTRY


def test_tool_catalog_search_finds_specialized_tools_without_exposing_everything():
    from tool_runtime.canonical_registry import _handler_tool_catalog_search
    from tool_runtime.schemas import ToolInvocation

    result = _handler_tool_catalog_search(ToolInvocation(
        tool_id="tool.catalog.search",
        arguments={"query": "创建一个 skill 并加载到当前会话", "limit": 6},
    ))

    assert result["ok"] is True
    load_ids = result["data"]["load_tool_ids"]
    assert "skill.create" in load_ids
    assert "skill.load" in load_ids
    assert "network.pcap.parse" not in load_ids


def test_tool_catalog_search_treats_skill_category_as_group_hint():
    from tool_runtime.canonical_registry import _handler_tool_catalog_search
    from tool_runtime.schemas import ToolInvocation

    result = _handler_tool_catalog_search(ToolInvocation(
        tool_id="tool.catalog.search",
        arguments={"query": "创建加载 skill 需要哪些工具", "category": "skill", "limit": 6},
    ))

    load_ids = result["data"]["load_tool_ids"]
    assert "skill.create" in load_ids
    assert "skill.load" in load_ids


def test_tool_catalog_search_finds_pcap_alignment_tools():
    from tool_runtime.canonical_registry import _handler_tool_catalog_search
    from tool_runtime.schemas import ToolInvocation

    result = _handler_tool_catalog_search(ToolInvocation(
        tool_id="tool.catalog.search",
        arguments={"query": "分析 pcap 报文 TCP 重传、乱序、序列号对齐", "limit": 6},
    ))

    load_ids = result["data"]["load_tool_ids"]
    assert load_ids[0] == "network.pcap.align"
    assert "network.pcap.parse" in load_ids


def test_router_can_expand_current_turn_visibility_from_catalog_result():
    from agent.tools.registry import ToolRegistry
    from agent.tools.router import ToolRouter
    from agent.tools.schemas import ToolSpec

    registry = ToolRegistry()
    registry._specs = {
        tool_id: ToolSpec(tool_id=tool_id, name=tool_id, description=tool_id, input_schema={})
        for tool_id in ("tool.catalog.search", "skill.create", "skill.load", "network.pcap.parse")
    }

    router = ToolRouter.for_turn(registry, allowed_tool_ids=["tool.catalog.search"])
    assert {spec.real_tool_id for spec in router.model_visible_specs} == {"tool.catalog.search"}

    added = router.expand_dynamic_visibility(["skill.create", "skill.load", "missing.tool"])

    assert added == ["skill.create", "skill.load"]
    assert {spec.real_tool_id for spec in router.model_visible_specs} == {
        "tool.catalog.search",
        "skill.create",
        "skill.load",
    }


def test_runtime_loop_expands_visibility_after_catalog_search_result():
    from types import SimpleNamespace
    from agent.protocol.tool_result import ToolResult
    from agent.runtime.tool_execution.catalog_stage import expand_tools_from_catalog_result
    from agent.tools.registry import ToolRegistry
    from agent.tools.router import ToolRouter
    from agent.tools.schemas import ToolSpec

    registry = ToolRegistry()
    registry._specs = {
        tool_id: ToolSpec(tool_id=tool_id, name=tool_id, description=tool_id, input_schema={})
        for tool_id in ("tool.catalog.search", "skill.create", "skill.load")
    }
    router = ToolRouter.for_turn(registry, allowed_tool_ids=["tool.catalog.search"])
    context = SimpleNamespace(
        tool_router=router,
        visible_tool_ids=["tool.catalog.search"],
        metadata={},
    )
    result = ToolResult(
        tool_id="tool.catalog.search",
        ok=True,
        metadata={"tool_catalog_expansion": {
            "query": "创建 skill",
            "load_tool_ids": ["skill.create", "skill.load"],
        }},
    )
    emitter = SimpleNamespace(emit=lambda *args, **kwargs: None)
    session = SimpleNamespace(session_id="s1")
    turn = SimpleNamespace(turn_id="t1", warnings=[])

    added = expand_tools_from_catalog_result(result, context, session, turn, 1, None, emitter)

    assert added == ["skill.create", "skill.load"]
    assert context.visible_tool_ids == ["skill.create", "skill.load", "tool.catalog.search"]
    assert context.metadata["dynamic_tool_expansions"][0]["added_tool_ids"] == added


def test_router_accepts_common_tool_catalog_underscore_alias():
    from types import SimpleNamespace
    from agent.tools.registry import ToolRegistry
    from agent.tools.router import ToolRouter
    from agent.tools.schemas import ToolSpec

    registry = ToolRegistry()
    registry._specs = {
        "tool.catalog.search": ToolSpec(
            tool_id="tool.catalog.search",
            name="tool.catalog.search",
            description="Search tool catalog",
            input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
        )
    }
    router = ToolRouter.for_turn(registry, allowed_tool_ids=["tool.catalog.search"])

    call = router.build_tool_call(SimpleNamespace(
        id="call_alias",
        name="tool_catalog__search",
        arguments={"query": "创建 skill"},
    ))

    assert call.real_tool_id == "tool.catalog.search"


def test_runtime_prompt_uses_double_underscore_tool_name_rule_and_catalog_fallback():
    from agent.runtime.prompting.profile import PromptProfile

    prompt = PromptProfile.from_classify_intent(intent="assistant_chat", user_input="有没有创建并加载 skill 的工具").build()

    assert "web.search → web__search" in prompt
    assert "tool.catalog.search" in prompt
    assert "single underscore" not in prompt
