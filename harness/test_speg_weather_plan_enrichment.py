"""SPEG should repair obvious weather forecast omissions before execution."""

from __future__ import annotations

import asyncio


def test_speg_enriches_weather_days_and_location_from_user_text():
    from speg_engine.engine import SPEGEngine
    from speg_engine.models import SPEGConfig

    captured = []

    def llm_mock(**kwargs):
        system = str(kwargs.get("system") or "")
        if "execution planner" in system.lower():
            return (
                '{"nodes":[{"id":"weather","tool":"web.manage",'
                '"args":{"action":"weather"},"deps":[]}]}'
            )
        return "杭州未来十天天气已返回。"

    async def weather_handler(args):
        captured.append(dict(args))
        return {"ok": True, "summary": "ok", "forecast_daily": list(range(args["days"]))}

    registry = {
        "web.manage": {
            "description": "Web weather",
            "args_schema": {
                "type": "object",
                "required": ["action"],
                "properties": {
                    "action": {"type": "string", "enum": ["search", "weather", "page"]},
                    "location": {"type": "string"},
                    "days": {"type": "integer"},
                },
            },
        }
    }
    engine = SPEGEngine(
        config=SPEGConfig(enable_finalizer=False),
        llm_invoke=llm_mock,
        tool_registry=registry,
    )
    engine.register_tool("web.manage", weather_handler, args_schema=registry["web.manage"]["args_schema"])

    result = asyncio.run(engine.run("查看未来十天杭州天气", workspace_id="default"))

    assert result.success is True
    assert captured == [{"action": "weather", "days": 10, "location": "杭州"}]
    events = result.metadata.get("plan_enrichment_events") or []
    assert {e["field"] for e in events} == {"days", "location"}
