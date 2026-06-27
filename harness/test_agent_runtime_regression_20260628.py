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
        captured["tool_count"] = len(restricted_tool_router.model_visible_tools())
        return FakeResult()

    monkeypatch.setattr(runtime_loop, "run_turn", fake_run_turn)
    result = subagent.run_subagent_task(created["subtask_id"], "ws_sub_budget")

    assert result["ok"] is True
    assert captured["is_sub_agent"] is True
    assert captured["max_steps"] == subagent.get_profile("review_agent").max_steps
    assert captured["tool_count"] > 0
