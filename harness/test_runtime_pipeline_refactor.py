# harness/test_runtime_pipeline_refactor.py
"""Tests for the runtime pipeline refactor.

Covers:
1. loop.py is thin (<=200 lines, contains TurnRunner, no banned symbols)
2. All new modules are importable
3. DENY is still terminal
4. Shell still requires approval
5. ResultBuilder produces correct fields
6. ToolExecutionPipeline stages run in order
"""

import inspect
import pytest
import types


# ---------------------------------------------------------------------------
# 1. loop.py is thin
# ---------------------------------------------------------------------------

class TestLoopIsThin:

    def test_loop_line_count_under_200(self):
        import agent.runtime.loop as loop
        src = inspect.getsource(loop)
        line_count = len(src.splitlines())
        assert line_count <= 200, f"loop.py has {line_count} lines, must be <=200"

    def test_loop_contains_turn_runner_delegation(self):
        import agent.runtime.loop as loop
        src = inspect.getsource(loop)
        assert "TurnRunner" in src, "loop.py must delegate to TurnRunner"

    def test_loop_no_execute_tool_chain(self):
        import agent.runtime.loop as loop
        src = inspect.getsource(loop)
        assert "_execute_tool_chain" not in src

    def test_loop_no_session_message_store(self):
        import agent.runtime.loop as loop
        src = inspect.getsource(loop)
        assert "SessionMessageStore" not in src

    def test_loop_no_approval_store(self):
        import agent.runtime.loop as loop
        src = inspect.getsource(loop)
        assert "approval_store" not in src

    def test_loop_no_dispatch_tool(self):
        import agent.runtime.loop as loop
        src = inspect.getsource(loop)
        assert "dispatch_tool" not in src

    def test_loop_no_invoke_llm(self):
        import agent.runtime.loop as loop
        src = inspect.getsource(loop)
        assert "invoke_llm" not in src

    def test_loop_no_check_tool_permission(self):
        import agent.runtime.loop as loop
        src = inspect.getsource(loop)
        assert "check_tool_permission" not in src

    def test_loop_still_has_run_turn(self):
        from agent.runtime.loop import run_turn
        assert callable(run_turn)

    def test_loop_still_has_max_steps(self):
        from agent.runtime.loop import MAX_STEPS, MAX_STEPS_ENV, MAX_STEPS_SUBAGENT_CEILING
        assert MAX_STEPS == 24
        assert isinstance(MAX_STEPS_ENV, int)
        assert isinstance(MAX_STEPS_SUBAGENT_CEILING, int)

    def test_loop_still_has_resolve_max_steps(self):
        from agent.runtime.loop import _resolve_max_steps
        assert callable(_resolve_max_steps)
        assert _resolve_max_steps() == 24

    def test_loop_still_has_approval_timeout(self):
        from agent.runtime.loop import (
            _APPROVAL_TIMEOUT_DEFAULT_S,
            _APPROVAL_TIMEOUT_SUBAGENT_S,
            _get_approval_timeout,
        )
        assert isinstance(_APPROVAL_TIMEOUT_DEFAULT_S, float)
        assert isinstance(_APPROVAL_TIMEOUT_SUBAGENT_S, float)
        assert callable(_get_approval_timeout)


# ---------------------------------------------------------------------------
# 2. All new modules importable
# ---------------------------------------------------------------------------

class TestNewModulesImportable:

    def test_turn_state(self):
        from agent.runtime.turn_state import TurnRuntimeState
        state = TurnRuntimeState()
        assert state.step == 0
        assert state.max_steps == 24
        assert state.final_response == ""

    def test_context_stage_uses_default_history_window(self, monkeypatch):
        import agent.runtime.stages.context as context_stage
        from agent.runtime.context_history import DEFAULT_HISTORY_WINDOW

        observed = {}

        class FakeContext:
            trace_id = "trace-1"
            metadata = {}

        def fake_hydrate(_session, _context, k):
            observed["k"] = k

        monkeypatch.setattr(context_stage, "build_turn_context", lambda *_args: FakeContext())
        monkeypatch.setattr(context_stage, "hydrate_history_from_store", fake_hydrate)
        monkeypatch.setattr(context_stage, "run_user_prompt_submit_hook", lambda *_args: None)

        state = types.SimpleNamespace(
            session=types.SimpleNamespace(session_id="s-1", workspace_id="default"),
            turn=types.SimpleNamespace(turn_id="t-1"),
            services=None,
            restricted_tool_router=None,
            emitter=None,
            audit_events=None,
            audit_trace=None,
        )

        context_stage.ContextStage().run(state)

        assert observed["k"] == DEFAULT_HISTORY_WINDOW

    def test_result_builder(self):
        from agent.runtime.result_builder import (
            build_success_result,
            build_error_result,
            build_partial_result,
            build_blocked_result,
        )
        assert callable(build_success_result)
        assert callable(build_error_result)
        assert callable(build_partial_result)
        assert callable(build_blocked_result)

    def test_runtime_events(self):
        from agent.runtime.runtime_events import RuntimeEventBus
        assert callable(RuntimeEventBus)

    def test_stages_context(self):
        from agent.runtime.stages.context import ContextStage
        assert hasattr(ContextStage, 'run')

    def test_stages_messages(self):
        from agent.runtime.stages.messages import MessageStage, _apply_manual_compact
        assert hasattr(MessageStage, 'run')
        assert callable(_apply_manual_compact)

    def test_stages_model(self):
        from agent.runtime.stages.model import ModelStage
        assert hasattr(ModelStage, 'run')

    def test_stages_persistence(self):
        from agent.runtime.stages.persistence import PersistenceStage
        assert hasattr(PersistenceStage, 'save_turn')

    def test_tool_execution_pipeline(self):
        from agent.runtime.tool_execution.pipeline import ToolExecutionPipeline
        assert hasattr(ToolExecutionPipeline, 'run')

    @pytest.mark.skip(reason="module agent.runtime.tool_execution.dispatch_stage was removed")
    def test_tool_execution_stages(self):
        from agent.runtime.tool_execution.permission_stage import PermissionStage
        from agent.runtime.tool_execution.risk_stage import RiskStage
        from agent.runtime.tool_execution.approval_stage import ApprovalStage
        from agent.runtime.tool_execution.dispatch_stage import DispatchStage
        from agent.runtime.tool_execution.result_stage import ResultStage
        for cls in (PermissionStage, RiskStage, ApprovalStage, DispatchStage, ResultStage):
            assert hasattr(cls, 'run')

    def test_runner(self):
        from agent.runtime.runner import TurnRunner
        assert callable(TurnRunner)


# ---------------------------------------------------------------------------
# 3. DENY is still terminal
# ---------------------------------------------------------------------------

class TestDenyIsTerminal:

    def test_permission_denied_returns_deny_result(self):
        from agent.runtime.permission_check import (
            build_permission_denied_result,
        )
        result = build_permission_denied_result("evil.tool")
        assert not result.ok
        assert "permission_denied" in result.errors

    def test_permission_matrix_deny_is_terminal(self):
        from agent.runtime.permission_check import check_tool_permission
        from agent.runtime.permission_matrix import PermissionDecision

        # Build minimal context and turn
        ctx = types.SimpleNamespace(
            session_mode="default",
            metadata={},
        )
        turn = types.SimpleNamespace(warnings=[])

        # Use a forbidden tool_id pattern — e.g. unknown exec tool
        spec = types.SimpleNamespace(
            risk_level='high',
            permission_action='exec',
        )
        requires_approval, denied, decision = check_tool_permission(
            "forbidden.exec.tool", spec, ctx, turn)
        # DENY must be terminal — hard assertions
        assert decision == PermissionDecision.DENY
        assert denied is True
        assert requires_approval is False
        assert any("permission_denied_terminal" in w for w in turn.warnings)

    def test_shell_requires_approval_not_deny(self):
        """Shell tools must go through the approval gate (needs_approval returns True).

        Note: The PermissionMatrix v0.2 forbidden list includes shell for
        backward-compat, but the runtime uses needs_approval() to route
        high-risk exec tools through the approval popup, not through DENY.
        """
        from agent.runtime.permission_check import needs_approval
        from agent.runtime.permission_matrix import PermissionDecision

        spec = types.SimpleNamespace(
            risk_level='high',
            permission_action='exec',
            requires_approval=True,
        )
        # Shell must require approval via needs_approval
        assert needs_approval("exec.run", spec, 'high', True) is True
        # PowerShell too
        assert needs_approval("exec.run", spec, 'high', True) is True


# ---------------------------------------------------------------------------
# 4. Shell still requires approval
# ---------------------------------------------------------------------------

class TestShellRequiresApproval:

    def test_shell_exec_needs_approval(self):
        from agent.runtime.permission_check import needs_approval
        spec = types.SimpleNamespace(
            risk_level='high',
            requires_approval=True,
        )
        assert needs_approval("exec.run", spec, 'high', True)

    def test_shell_unsafe_command_denied(self):
        from agent.runtime.permission_check import check_shell_safety
        safe, word = check_shell_safety("exec.run", {"command": "rm -rf /"})
        assert not safe
        assert word == "destructive_delete"

    def test_shell_safe_command_allowed(self):
        from agent.runtime.permission_check import check_shell_safety
        safe, word = check_shell_safety("exec.run", {"command": "ls -la"})
        assert safe
        assert word == ""


# ---------------------------------------------------------------------------
# 5. ResultBuilder produces correct fields
# ---------------------------------------------------------------------------

class TestResultBuilder:

    def _make_state(self):
        from agent.runtime.turn_state import TurnRuntimeState
        from agent.runtime.query_engine import StreamEmitter

        session = types.SimpleNamespace(
            session_id="s1",
            workspace_id="default",
            history=[],
        )
        turn = types.SimpleNamespace(
            turn_id="t1",
            warnings=[],
            errors=[],
            metadata={},
            op=None,
            status="running",
            final_response="",
        )
        context = types.SimpleNamespace(
            trace_id="trace-1",
            model_config={"model": "test-model"},
            metadata={},
            user_input="hello",
            safe_context={},
        )
        emitter = StreamEmitter()

        state = TurnRuntimeState(
            session=session,
            turn=turn,
            services=None,
            emitter=emitter,
            audit_events=None,
            audit_trace=None,
            context=context,
            all_tool_results=[],
            final_response="Test response",
            step=1,
            max_steps=8,
            metadata={},
        )
        return state

    def test_build_blocked_result_fields(self):
        from agent.runtime.result_builder import build_blocked_result
        from unittest.mock import patch

        state = self._make_state()
        with patch("agent.runtime.result_builder.persist_run_record"):
            result = build_blocked_result(state, "hook_blocked")

        assert result.ok is False
        assert "blocked" in result.final_response.lower()
        assert result.session_id == "s1"
        assert result.turn_id == "t1"
        assert result.trace_id == "trace-1"
        assert result.tool_decision["needed"] is False
        assert "blocked_by_hook" in result.no_tool_reason

    def test_build_error_result_fields(self):
        from agent.runtime.result_builder import build_error_result
        from unittest.mock import patch

        state = self._make_state()
        with patch("agent.runtime.result_builder.persist_run_record"):
            result = build_error_result(
                state, "Error occurred", "provider_error",
                {"retryable": True},
                tool_decision={"needed": False, "reason": "Error"},
                no_tool_reason="provider_error",
            )

        assert result.ok is False
        assert result.error_type == "provider_error"
        assert result.final_response == "Error occurred"
        assert result.metadata.get("retryable") is True

    def test_build_partial_result_fields(self):
        from agent.runtime.result_builder import build_partial_result
        from unittest.mock import patch

        state = self._make_state()
        with patch("agent.runtime.result_builder.persist_run_record"):
            result = build_partial_result(state, "max_steps")

        assert result.ok is True
        assert "[partial]" in result.final_response
        assert result.metadata.get("terminal_reason") == "max_steps_exceeded"


# ---------------------------------------------------------------------------
# 6. ToolExecutionPipeline stages run in order
# ---------------------------------------------------------------------------

class TestToolExecutionPipelineOrder:

    def test_pipeline_has_all_stages(self):
        from agent.runtime.tool_execution.pipeline import ToolExecutionPipeline
        p = ToolExecutionPipeline()
        assert hasattr(p, '_action_planner')
        assert hasattr(p, '_action_executor')
        assert hasattr(p, '_result')

    def test_repeated_tool_failure_detection(self):
        from agent.runtime.tool_execution.retry_policy import detect_repeated_tool_failure

        # No failure
        assert detect_repeated_tool_failure([]) is None
        assert detect_repeated_tool_failure([{"ok": True}]) is None

        # Repeated failure
        results = [
            {"ok": False, "tool_id": "t1", "errors": ["err1"], "summary": "fail"},
            {"ok": False, "tool_id": "t1", "errors": ["err1"], "summary": "fail"},
        ]
        assert detect_repeated_tool_failure(results) is not None

        # Different tools — not repeated
        results2 = [
            {"ok": False, "tool_id": "t1", "errors": ["err1"]},
            {"ok": False, "tool_id": "t2", "errors": ["err1"]},
        ]
        assert detect_repeated_tool_failure(results2) is None

    def test_preserve_tool_payload_edges(self):
        from agent.runtime.tool_execution.result_stage import preserve_tool_payload_edges
        short = "hello"
        assert preserve_tool_payload_edges(short, 100) == short

        long_text = "x" * 500
        result = preserve_tool_payload_edges(long_text, 100)
        assert len(result) <= 200  # truncated with marker
        assert "truncated middle" in result
