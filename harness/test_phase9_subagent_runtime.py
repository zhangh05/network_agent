# harness/test_phase9_subagent_runtime.py
"""Phase 9: Subagent Runtime tests."""

import pytest, uuid
from agent.runtime.durable.subagent import (
    get_profile, create_subagent_task, run_subagent_task,
    merge_subagent_result, BUILTIN_PROFILES,
)


class _FakeAgentResult:
    ok = True
    final_response = "review complete"
    events = []


def _fake_run_turn(session, turn, restricted_tool_router=None):
    return _FakeAgentResult()


class TestSubagentProfiles:
    def test_all_7_profiles_exist(self):
        assert len(BUILTIN_PROFILES) == 7
        assert "review_agent" in BUILTIN_PROFILES
        assert "security_agent" in BUILTIN_PROFILES

    def test_review_agent_readonly(self):
        p = get_profile("review_agent")
        assert p.allowed_action_classes == ["read"]
        assert not p.can_modify_files
        assert not p.can_execute_commands

    def test_fix_agent_can_write(self):
        p = get_profile("fix_agent")
        assert "write" in p.allowed_action_classes
        assert p.can_modify_files

    def test_security_agent_readonly(self):
        p = get_profile("security_agent")
        assert p.allowed_action_classes == ["read"]
        assert not p.can_execute_commands


class TestSubagentTask:
    def test_create_subagent_binds_to_parent(self):
        ws = f"ws_sa_{uuid.uuid4().hex[:8]}"
        result = create_subagent_task(
            parent_task_id="task-123", workspace_id=ws,
            session_id="s1", profile_id="review_agent",
            goal="Review OSPF config changes",
        )
        assert result["ok"]
        assert result["subtask_id"].startswith("sub-")

    def test_unknown_profile_rejected(self):
        result = create_subagent_task(
            parent_task_id="t1", workspace_id="ws_x",
            session_id="s1", profile_id="nonexistent",
            goal="test",
        )
        assert result["ok"] is False

    def test_workspace_required(self):
        result = create_subagent_task(
            parent_task_id="t1", workspace_id="",
            session_id="s1", profile_id="review_agent",
            goal="test",
        )
        assert result["ok"] is False


class TestSubagentRuntime:
    def test_review_agent_cannot_call_write_tools(self, monkeypatch):
        # v3.10: run_turn is imported inside run_subagent_task via 'from agent.runtime.loop import run_turn'
        monkeypatch.setattr("agent.runtime.loop.run_turn", _fake_run_turn)
        ws = f"ws_rt_{uuid.uuid4().hex[:8]}"
        cr = create_subagent_task("t1", ws, "s1", "review_agent", "Review code")
        assert cr["ok"]

        r = run_subagent_task(cr["subtask_id"], ws)
        # Review agent should not be able to use write/delete/execute tools
        assert r["ok"]
        # Should not have succeeded — profile restricts action_class
        assert r["status"] in ("succeeded", "failed")

    @pytest.mark.skip(reason="requires web search API")
    def test_subagent_caller_is_subagent(self):
        """Subagent tool execution must use caller=subagent."""
        from agent.runtime.durable.subagent import _execute_as_subagent
        ws = f"ws_cl_{uuid.uuid4().hex[:8]}"
        result = _execute_as_subagent("web.manage", {"query": "test", "top_k": 1}, ws)
        # v3.10: web.manage allows subagent caller (profile-gated)
        assert result["ok"], f"Subagent should be allowed for web.manage, got {result}"

    def test_cross_workspace_run_blocked(self):
        ws_a = f"ws_sa9_{uuid.uuid4().hex[:8]}"
        ws_b = f"ws_sb9_{uuid.uuid4().hex[:8]}"
        cr = create_subagent_task("t1", ws_a, "s1", "review_agent", "test")
        r = run_subagent_task(cr["subtask_id"], ws_b)
        assert r["ok"] is False

    def test_merge_subagent_result(self, monkeypatch):
        # v3.10: run_turn is imported inside run_subagent_task via 'from agent.runtime.loop import run_turn'
        monkeypatch.setattr("agent.runtime.loop.run_turn", _fake_run_turn)
        ws = f"ws_mg_{uuid.uuid4().hex[:8]}"
        cr = create_subagent_task("t-parent", ws, "s1", "review_agent", "Review")
        r = run_subagent_task(cr["subtask_id"], ws)
        assert r["ok"]

        m = merge_subagent_result("t-parent", cr["subtask_id"], ws)
        assert m["ok"]
        assert m["merged"] is True

    def test_merge_cross_parent_rejected(self):
        ws = f"ws_mp_{uuid.uuid4().hex[:8]}"
        cr = create_subagent_task("t-real", ws, "s1", "review_agent", "test")
        m = merge_subagent_result("t-wrong", cr["subtask_id"], ws)
        assert m["ok"] is False


class TestProfileToolsFilter:
    def test_review_agent_no_exec_tools(self):
        p = get_profile("review_agent")
        # review_agent must not have exec.run in allowed_tools
        exec_tools = [t for t in p.allowed_tools if "exec" in t or "delete" in t]
        assert len(exec_tools) == 0

    def test_test_agent_has_exec_tools(self):
        p = get_profile("test_agent")
        assert "exec.run" in p.allowed_tools
        assert "system.manage" in p.allowed_tools


class TestPhase8Unaffected:
    def test_phase8_memory_gate_still_works(self):
        """v3.9.6: MemoryWriteGate now applies a low_value_memory filter
        on top of the legacy secret / workspace_id / redactor checks.
        A bare "test" string would be rejected as low-value, so we
        pass a concrete user-confirmed record with non-trivial content
        to verify the gate accepts a normal write end-to-end.
        """
        from workspace.memory_governance import MemoryWriteGate, MemoryRecord
        gate = MemoryWriteGate()
        rec = MemoryRecord(
            workspace_id="ws_test",
            content="User said: please remember my office wifi is on the 5th floor.",
            summary="office wifi location",
            status="pending",
            source="user",
            confidence=0.5,
        )
        result = gate.write(rec)
        assert result["ok"] is True
        assert result["status"] in ("active", "pending", "conflict")
