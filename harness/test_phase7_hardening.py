# harness/test_phase7_hardening.py
"""Phase 7 follow-up: workspace boundary hardening."""

import pytest, uuid


class TestNoDefaultFallbacks:
    def test_agentop_no_default(self):
        from agent.protocol.op import AgentOp
        op = AgentOp()
        assert op.workspace_id == ""

    def test_facade_restore_no_default(self):
        """_restore_session_history no longer falls back to 'default'."""
        import agent.app.facade as fac
        source = open(fac.__file__).read()
        assert 'or "default"' not in source

    def test_hook_runner_no_default(self):
        import agent.runtime.hook_runner as hr
        source = open(hr.__file__).read()
        assert "or 'default'" not in source and "'default'" not in source

    def test_memory_write_no_default(self):
        import agent.runtime.memory_write.llm_memory as lm
        import agent.runtime.memory_write.llm_gate as lg
        lm_src = open(lm.__file__).read()
        lg_src = open(lg.__file__).read()
        assert '"default"' not in lm_src
        assert '"default"' not in lg_src

    def test_default_hooks_no_default(self):
        import agent.runtime.default_hooks as dh
        source = open(dh.__file__).read()
        assert '"default"' not in source

    def test_context_pipeline_no_default(self):
        import agent.runtime.context_pipeline.pipeline as cp
        source = open(cp.__file__).read()
        assert '"default"' not in source


class TestExistingUnaffected:
    def test_phase7_basic(self):
        from agent.runtime.durable.store import save_task, get_task
        from agent.runtime.durable.models import TaskState
        ws = f"ws_h7_{uuid.uuid4().hex[:8]}"
        task = TaskState.new(workspace_id=ws, session_id="s1")
        save_task(task)
        assert get_task(ws, task.task_id) is not None

    def test_phase6_basic(self):
        from core.tools.manifest_registry import get_manifest
        assert get_manifest("web.manage") is not None

    def test_approval_basic(self):
        from agent.approval import get_approval_store
        assert get_approval_store()
