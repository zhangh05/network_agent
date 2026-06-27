"""Regression tests for subagent dispatch and tool registry visibility."""

from __future__ import annotations


def test_canonical_registry_import_has_no_general_tools_cycle():
    from tool_runtime.canonical_registry import get_entry, to_tool_specs

    specs = to_tool_specs()
    assert specs
    assert get_entry("agent.spawn") is not None


def test_subagent_cannot_spawn_nested_agents():
    from tool_runtime.manifest_registry import get_manifest

    assert "subagent" not in get_manifest("agent.spawn").allowed_callers
    assert "subagent" not in get_manifest("agent.team.run").allowed_callers


def test_subagent_turn_receives_profile_step_budget(monkeypatch, tmp_path):
    import agent.runtime.durable.subagent as subagent
    import agent.runtime.loop as runtime_loop
    import workspace.run_store as run_store

    monkeypatch.setattr(run_store, "WS_ROOT", tmp_path)
    created = subagent.create_subagent_task(
        parent_task_id="parent-1",
        workspace_id="ws_sub_budget",
        session_id="sess-1",
        profile_id="review_agent",
        goal="Review the current state.",
    )
    assert created["ok"] is True

    captured = {}

    class FakeResult:
        ok = True
        final_response = "review complete"
        events = []

    def fake_run_turn(session, turn, services=None, restricted_tool_router=None):
        captured["max_steps"] = getattr(turn, "metadata", {}).get("max_steps")
        captured["is_sub_agent"] = session.is_sub_agent
        captured["session_id"] = session.session_id
        captured["op_session_id"] = turn.op.session_id
        captured["tool_count"] = len(restricted_tool_router.model_visible_tools())
        return FakeResult()

    monkeypatch.setattr(runtime_loop, "run_turn", fake_run_turn)
    result = subagent.run_subagent_task(created["subtask_id"], "ws_sub_budget")

    assert result["ok"] is True
    assert captured["is_sub_agent"] is True
    assert captured["session_id"] == created["subtask_id"]
    assert captured["op_session_id"] == created["subtask_id"]
    assert captured["session_id"] != "sess-1"
    assert captured["max_steps"] == subagent.get_profile("review_agent").max_steps
    assert captured["tool_count"] > 0
    assert "web.search" in subagent.get_profile("review_agent").allowed_tools


def test_web_private_url_guard_has_prefix_constants():
    from tool_runtime.general_tools.shared_web import _is_private_url

    assert _is_private_url("http://192.168.1.1/index.html") is True
    assert _is_private_url("https://www.rfc-editor.org/rfc/rfc4271") is False


def test_web_page_process_cache_clock_available(monkeypatch):
    from tool_runtime.general_tools.web_tools import handle_web_fetch_summary
    from tool_runtime.schemas import ToolInvocation
    import requests
    import socket

    class FakeResponse:
        status_code = 200
        url = "https://example.com/bgp"
        history = []
        encoding = "utf-8"
        apparent_encoding = "utf-8"
        text = "<html><head><title>BGP</title></head><body><p>BGP uses TCP port 179.</p></body></html>"

    monkeypatch.setattr(socket, "gethostbyname", lambda _host: "93.184.216.34")
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: FakeResponse())

    result = handle_web_fetch_summary(ToolInvocation(
        tool_id="web.page.process",
        arguments={"url": "https://example.com/bgp"},
        workspace_id="ws_web_page",
        requested_by="turn_runner",
    ))

    assert result["ok"] is True
    assert "BGP uses TCP port 179" in result["summary"]


def test_tool_catalog_search_tolerates_empty_namespace_fields(monkeypatch):
    from tool_runtime.canonical_registry import _handler_tool_catalog_search
    from tool_runtime.schemas import ToolInvocation
    import tool_runtime.canonical_registry as registry
    import tool_runtime.tool_governance as governance
    import tool_runtime.tool_namespace as namespace

    class FakeNamespace:
        category = "web"
        group = "search"
        action = "search"
        display_name = "Fake Web Search"
        short_label = None
        usage_hint = None
        not_for = None

    class FakeEntry:
        risk_level = "low"
        requires_approval = False
        description = None

    monkeypatch.setattr(namespace, "TOOL_NAMESPACE", {"fake.web": FakeNamespace()})
    monkeypatch.setattr(governance, "TOOL_GOVERNANCE", {})
    monkeypatch.setattr(registry, "CANONICAL_REGISTRY", {"fake.web": FakeEntry()})

    result = _handler_tool_catalog_search(ToolInvocation(
        tool_id="tool.catalog.search",
        arguments={"query": "web search"},
        workspace_id="ws_catalog",
        requested_by="turn_runner",
    ))

    assert result["ok"] is True
    assert result["data"]["load_tool_ids"] == ["fake.web"]


def test_agent_spawn_inherits_invocation_session(monkeypatch):
    from tool_runtime.general_tools.agent_tools import handle_agent_spawn
    from tool_runtime.schemas import ToolInvocation
    import tool_runtime.general_tools.agent_tools as agent_tools

    captured = {}

    def fake_run_durable_subagent(**kwargs):
        captured.update(kwargs)
        return {"ok": True, "summary": "done", "status": "succeeded"}

    monkeypatch.setattr(agent_tools, "_run_durable_subagent", fake_run_durable_subagent)

    result = handle_agent_spawn(ToolInvocation(
        tool_id="agent.spawn",
        arguments={"instruction": "research"},
        workspace_id="ws_spawn",
        session_id="parent-session",
        requested_by="turn_runner",
    ))

    assert result["ok"] is True
    assert captured["session_id"] == "parent-session"


def test_tool_runtime_context_carries_session_to_invocation(monkeypatch):
    from tool_runtime.client import ToolRuntimeClient
    from tool_runtime.context import ToolRuntimeContext
    from tool_runtime.registry import ToolRegistry
    from tool_runtime.schemas import ToolSpec

    captured = {}
    registry = ToolRegistry()

    def fake_handler(inv):
        captured["session_id"] = inv.session_id
        return {"ok": True}

    registry.register_tool(
        ToolSpec(
            tool_id="web.search",
            category="web",
            input_schema={"type": "object", "properties": {}},
        ),
        fake_handler,
    )

    result = ToolRuntimeClient(registry).invoke(
        "web.search",
        {},
        context=ToolRuntimeContext(
            workspace_id="default",
            session_id="sess-runtime",
            requested_by="turn_runner",
        ),
    )

    assert result.status == "succeeded"
    assert captured["session_id"] == "sess-runtime"


def test_action_result_projection_preserves_tool_output_for_llm():
    from agent.runtime.actions.models import ActionResult
    from agent.runtime.actions.result import action_result_to_tool_result
    from agent.runtime.tool_result_utils import build_tool_message_payload

    action = ActionResult(
        tool_call_id="call-1",
        tool_id="agent.spawn",
        ok=True,
        status="success",
        normalized_result={
            "ok": True,
            "summary": "subagent complete",
            "output": {
                "final_response": "完整子 agent 结论",
                "subtask_id": "sub-abc",
            },
        },
    )

    tool_result = action_result_to_tool_result(action)
    payload = build_tool_message_payload(tool_result)

    assert payload["final_response"] == "完整子 agent 结论"
    assert payload["subtask_id"] == "sub-abc"
