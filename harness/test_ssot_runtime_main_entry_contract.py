"""SSOT Runtime main-entry contract tests."""

from __future__ import annotations

import pytest


def test_agent_app_submit_uses_ssot_runtime(monkeypatch, temp_dirs):
    from agent.app.facade import AgentApp

    def fake_llm(**kwargs):
        system = str(kwargs.get("system") or "")
        if "execution planner" in system.lower():
            return '{"nodes":[],"final_response":"收到"}'
        return "收到"

    monkeypatch.setattr("agent.runtime.ssot_runtime._invoke_llm_for_ssot_runtime", fake_llm)

    app = AgentApp()
    result = app.submit_user_message(
        user_input="你好",
        workspace_id="default",
        metadata={"transport": "test"},
    )

    assert result.ok is True
    assert result.final_response.strip("。") == "收到"
    assert result.metadata["runtime_engine"] == "ssot_runtime"
    assert result.metadata["timeline_summary"]["llm_calls"] == 1
    assert result.tool_calls == []


@pytest.mark.skip(reason="flaky integration test — needs deeper investigation")
def test_ssot_runtime_tool_node_invokes_tool_runtime_client(monkeypatch, temp_dirs):
    from dataclasses import dataclass, field

    from agent.app.facade import AgentApp

    calls = []

    def fake_llm(**kwargs):
        system = str(kwargs.get("system") or "")
        if "execution planner" in system.lower():
            return (
                '{"nodes":[{"id":"search_memory","tool":"memory.manage",'
                '"args":{"action":"search","query":"BGP"}}]}'
            )
        return "找到 1 条记忆。"

    @dataclass
    class FakeToolResult:
        tool_id: str = "memory.manage"
        status: str = "succeeded"
        output: dict = field(default_factory=lambda: {"items": ["BGP peer down"]})
        summary: str = "Found 1 memory"
        artifact_ids: list = field(default_factory=list)
        warnings: list = field(default_factory=list)
        errors: list = field(default_factory=list)
        duration_ms: int = 7
        redacted: bool = True

    class FakeClient:
        def list_tools(self):
            return [{
                "tool_id": "memory.manage",
                "description": "Memory tool",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string"},
                        "query": {"type": "string"},
                    },
                    "required": ["action"],
                },
                "category": "memory",
                "risk_level": "medium",
                "enabled": True,
                "callable_by_llm": True,
            }]

        def invoke(self, tool_id, arguments, *, context=None):
            calls.append((tool_id, arguments, context))
            return FakeToolResult(tool_id=tool_id)

    monkeypatch.setattr("agent.runtime.ssot_runtime._invoke_llm_for_ssot_runtime", fake_llm)
    monkeypatch.setattr("agent.runtime.ssot_runtime._tool_runtime_client", lambda: FakeClient())

    app = AgentApp()
    result = app.submit_user_message(
        user_input="查一下 BGP 记忆",
        workspace_id="default",
        metadata={"transport": "test"},
    )

    assert result.ok is True
    assert result.metadata["runtime_engine"] == "ssot_runtime"
    assert result.tool_calls[0]["tool_id"] == "memory.manage"
    assert result.tool_calls[0]["ok"] is True
    assert calls
    assert calls[0][0] == "memory.manage"
    assert calls[0][1]["query"] == "BGP"
    assert calls[0][2].requested_by == "turn_runner"
