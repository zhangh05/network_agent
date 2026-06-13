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
