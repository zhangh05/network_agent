"""Full tool availability contract.

The LLM should see every useful tool. Risk is carried by metadata and policy,
not by hiding callable tools from the model.
"""

from tool_runtime.schemas import ToolInvocation


def test_runtime_catalog_enables_all_general_tools():
    from tool_runtime.integration import get_default_tool_runtime_client

    client = get_default_tool_runtime_client()
    tools = client.list_tools()
    by_id = {t["tool_id"]: t for t in tools}

    assert len(tools) == 58
    for tool_id in (
        "weather.current",
        "weather.forecast",
        "news.search",
        "command.approved_exec",
        "powershell.approved_script",
    ):
        assert by_id[tool_id]["enabled"] is True
        assert by_id[tool_id]["callable_by_llm"] is True

    assert by_id["command.approved_exec"]["risk_level"] == "high"
    assert by_id["command.approved_exec"]["requires_approval"] is True
    assert by_id["powershell.approved_script"]["risk_level"] == "high"
    assert by_id["powershell.approved_script"]["requires_approval"] is True


def test_agent_exposes_all_llm_callable_tools_with_risk_metadata():
    from agent.runtime.services import default_runtime_services

    router = default_runtime_services().tool_service
    tools = router.model_visible_tools()
    names = {t["function"]["name"] for t in tools}
    descriptions = {
        t["function"]["name"]: t["function"]["description"]
        for t in tools
    }

    assert len(router.registry.list_all()) == 76
    assert len(tools) == 75
    assert "knowledge__read_source" not in names

    for llm_name in (
        "weather__current",
        "weather__forecast",
        "news__search",
        "command__approved_exec",
        "powershell__approved_script",
    ):
        assert llm_name in names

    assert "risk=high" in descriptions["command__approved_exec"]
    assert "approval=required" in descriptions["command__approved_exec"]
    assert "allowlisted" in descriptions["command__approved_exec"]


def test_llm_tool_descriptions_preserve_full_runtime_guidance():
    from agent.runtime.services import default_runtime_services
    from tool_runtime.integration import get_default_tool_runtime_client

    runtime_desc = get_default_tool_runtime_client().get_tool("web.search")["description"]
    assert "anything that may have changed" in runtime_desc
    assert not runtime_desc.endswith("or any")

    router = default_runtime_services().tool_service
    descriptions = {
        t["function"]["name"]: t["function"]["description"]
        for t in router.model_visible_tools()
    }
    assert "anything that may have changed" in descriptions["web__search"]
    assert not descriptions["web__search"].endswith("or any")


def test_llm_tool_parameters_are_normalized_for_function_calling():
    from agent.runtime.services import default_runtime_services

    tools = default_runtime_services().tool_service.model_visible_tools()
    by_name = {t["function"]["name"]: t["function"]["parameters"] for t in tools}

    assert by_name["command__dry_run_echo"] == {
        "type": "object",
        "properties": {},
        "required": [],
    }

    for name, params in by_name.items():
        assert params["type"] == "object", name
        assert isinstance(params["properties"], dict), name
        assert isinstance(params["required"], list), name


def test_weather_and_news_tools_return_useful_web_backed_results(monkeypatch):
    from tool_runtime.general_tools import (
        handle_news_search,
        handle_weather_current,
        handle_weather_forecast,
    )

    calls = []

    def fake_web_search(inv):
        calls.append((inv.tool_id, dict(inv.arguments)))
        return {
            "ok": True,
            "summary": "Found 1 public web result(s)",
            "results": [{"title": "Example result", "url": "https://example.com", "citation": "[1] example.com"}],
            "count": 1,
            "results_markdown": "[1] Example result: https://example.com",
            "next_actions": ["Use citations."],
            "provider": "test",
        }

    monkeypatch.setattr("tool_runtime.general_tools.handle_web_search", fake_web_search)

    weather = handle_weather_current(ToolInvocation(
        tool_id="weather.current",
        arguments={"location": "Shanghai", "language": "zh-CN"},
    ))
    forecast = handle_weather_forecast(ToolInvocation(
        tool_id="weather.forecast",
        arguments={"location": "Shanghai", "days": 3},
    ))
    news = handle_news_search(ToolInvocation(
        tool_id="news.search",
        arguments={"query": "AI news", "top_k": 2, "recency": "day"},
    ))

    assert weather["ok"] is True
    assert forecast["ok"] is True
    assert news["ok"] is True
    assert weather["tool_fallback"] == "web.search"
    assert forecast["tool_fallback"] == "web.search"
    assert news["tool_fallback"] == "web.search"
    assert calls[0][1]["query"].startswith("Shanghai current weather")
    assert calls[1][1]["query"].startswith("Shanghai 3 day weather forecast")
    assert calls[2][1]["query"] == "AI news"


def test_high_risk_tools_are_visible_but_block_without_approval():
    from tool_runtime.executor import ToolExecutor
    from tool_runtime.general_tools import register_all_general_tools
    from tool_runtime.policy import ToolPolicy
    from tool_runtime.registry import ToolRegistry

    reg = register_all_general_tools(ToolRegistry())
    ex = ToolExecutor(reg, ToolPolicy())

    command = ex.execute(ToolInvocation(
        tool_id="command.approved_exec",
        arguments={"command_id": "system.platform_info"},
        workspace_id="default",
    ))
    ps = ex.execute(ToolInvocation(
        tool_id="powershell.approved_script",
        arguments={"script_id": "win.platform_info"},
        workspace_id="default",
    ))

    assert command.status == "blocked"
    assert command.policy_decision.requires_approval is True
    assert "approval_id" in command.summary
    assert ps.status == "blocked"
    assert ps.policy_decision.requires_approval is True
    assert "approval_id" in ps.summary


def test_client_forwards_trusted_context_approval_id_but_not_tool_argument():
    from tool_runtime.integration import get_default_tool_runtime_client
    from tool_runtime.context import ToolRuntimeContext

    client = get_default_tool_runtime_client()
    spec = client.get_tool("command.approved_exec")

    assert "approval_id" not in spec["input_schema"]["properties"]

    untrusted_arg = client.invoke(
        "command.approved_exec",
        {
            "command_id": "system.platform_info",
            "approval_id": "APR-UNTRUSTED-ARG",
        },
        dry_run=True,
    )
    assert untrusted_arg.status == "blocked"
    assert "approval_id" in untrusted_arg.summary

    trusted_context = client.invoke(
        "command.approved_exec",
        {"command_id": "system.platform_info"},
        dry_run=True,
        context=ToolRuntimeContext(approval_id="APR-UNIT-TEST"),
    )

    assert trusted_context.status == "dry_run"
    assert trusted_context.policy_decision.allowed is True


def test_approved_process_list_command_is_cross_platform_read_only():
    from tool_runtime.general_tools import handle_command_approved_exec

    result = handle_command_approved_exec(ToolInvocation(
        tool_id="command.approved_exec",
        arguments={"command_id": "system.process_list_safe"},
    ))

    assert result["ok"] is True
    assert "processes" in result
    assert isinstance(result["processes"], list)


def test_agent_dispatch_does_not_treat_llm_argument_as_trusted_approval_id():
    from agent.core.session import AgentSession
    from agent.core.turn import AgentTurn
    from agent.protocol.op import AgentOp
    from agent.protocol.tool_call import ToolCall
    from agent.runtime.context_builder import build_turn_context
    from agent.runtime.services import default_runtime_services

    ctx = build_turn_context(
        AgentSession(session_id="approval_forwarding", workspace_id="default"),
        AgentTurn(turn_id="approval_forwarding_turn", op=AgentOp(user_input="run approved platform info")),
        default_runtime_services(),
    )
    result = ctx.tool_router.dispatch(ToolCall(
        call_id="approval-forwarding-check",
        llm_tool_name="command__approved_exec",
        real_tool_id="command.approved_exec",
        arguments={
            "command_id": "system.platform_info",
            "approval_id": "APR-UNIT-TEST",
        },
    ), ctx)

    assert result.ok is False
    assert result.raw["status"] == "blocked"
    assert "approval_id" in result.summary
