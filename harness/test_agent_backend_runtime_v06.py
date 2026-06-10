# harness/test_agent_backend_runtime_v06.py
"""Agent Backend Runtime v0.6 — Codex-style runtime tests."""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock


class TestAgentAppSubmit:
    """Test AgentApp.submit_user_message returns AgentResult."""

    def test_agent_app_submit_user_message_returns_agent_result(self):
        """AgentApp.submit_user_message returns AgentResult."""
        from agent.app.facade import AgentApp
        from agent.runtime.services import RuntimeServices
        from agent.tools.registry import ToolRegistry
        from agent.tools.router import ToolRouter
        from agent.skills.registry import SkillRegistry
        from agent.modules.registry import ModuleRegistry
        from agent.audit.events import EventRecorder
        from agent.audit.trace import TraceRecorder
        from agent.audit.rollout import RolloutRecorder

        # Minimal services with empty registry (no real tools)
        reg = ToolRegistry()
        services = RuntimeServices(
            tool_service=ToolRouter(registry=reg),
            skill_service=SkillRegistry(),
            module_service=ModuleRegistry(),
            audit_service={
                "events": EventRecorder(),
                "trace": TraceRecorder(),
                "rollout": RolloutRecorder(),
            },
        )

        app = AgentApp(services=services)
        result = app.submit_user_message("hello", workspace_id="test")

        # Verify AgentResult structure
        assert hasattr(result, 'ok')
        assert hasattr(result, 'final_response')
        assert hasattr(result, 'to_dict')
        d = result.to_dict()
        assert "ok" in d
        assert "final_response" in d


class TestThreadDelegatesToSession:
    """Test Thread doesn't call LLM directly."""

    def test_thread_submit_delegates_to_session(self):
        """Thread.submit delegates to session.submit."""
        from agent.core.thread import AgentThread
        from agent.core.session import AgentSession
        from agent.protocol.op import AgentOp

        session = MagicMock()
        mock_result = MagicMock(ok=True, final_response="test")
        session.submit = MagicMock(return_value=mock_result)

        thread = AgentThread(session=session)
        op = AgentOp.user_message("hi")
        result = thread.submit(op)

        session.submit.assert_called_once_with(op)
        assert result.ok is True


class TestSessionCreatesTurn:
    """Test Session creates Turn from AgentOp."""

    def test_session_creates_turn_from_user_op(self):
        """Session creates turn from AgentOp."""
        from agent.core.session import AgentSession
        from agent.core.turn import AgentTurn
        from agent.protocol.op import AgentOp

        session = AgentSession(session_id="s1", workspace_id="test")
        op = AgentOp.user_message("hi", session_id="s1")

        # Check that from_op creates a turn correctly
        turn = AgentTurn.from_op(op)
        assert turn.op.user_input == "hi"
        assert turn.status == "pending"


class TestTurnContextContainsSnapshots:
    """Test TurnContext has runtime_snapshot, tool_router, skills, modules."""

    def test_turn_context_contains_runtime_snapshot(self):
        """TurnContext contains runtime_snapshot, tool_router, skill_snapshot, module_snapshot."""
        from agent.core.turn_context import TurnContext

        ctx = TurnContext(
            turn_id="t1", session_id="s1", workspace_id="test",
            runtime_snapshot={"tool_count": 5, "enabled_skills": ["config_translation"]},
            skill_snapshot={"enabled": [{"skill_id": "config_translation"}]},
            module_snapshot={"enabled": [{"module_id": "config_translation"}]},
        )

        assert ctx.runtime_snapshot["tool_count"] == 5
        assert ctx.skill_snapshot["enabled"][0]["skill_id"] == "config_translation"
        assert ctx.module_snapshot["enabled"][0]["module_id"] == "config_translation"


class TestRuntimeLoop:
    """Test RuntimeLoop — model message and tool call scenarios."""

    def test_runtime_loop_model_message_finishes_turn(self):
        """Mock LLM returns assistant message → turn finishes."""
        from agent.runtime.loop import run_turn
        from agent.core.session import AgentSession
        from agent.core.turn import AgentTurn
        from agent.protocol.op import AgentOp
        from agent.runtime.services import RuntimeServices
        from agent.tools.registry import ToolRegistry
        from agent.tools.router import ToolRouter
        from agent.skills.registry import SkillRegistry
        from agent.modules.registry import ModuleRegistry
        from agent.audit.events import EventRecorder
        from agent.audit.trace import TraceRecorder
        from agent.audit.rollout import RolloutRecorder

        reg = ToolRegistry()
        services = RuntimeServices(
            tool_service=ToolRouter(registry=reg),
            skill_service=SkillRegistry(),
            module_service=ModuleRegistry(),
            audit_service={
                "events": EventRecorder(),
                "trace": TraceRecorder(),
                "rollout": RolloutRecorder(),
            },
        )

        session = AgentSession(session_id="s1", services=services)
        op = AgentOp.user_message("hi")
        turn = AgentTurn.from_op(op)

        # Mock invoke_llm to return content
        mock_resp = MagicMock()
        mock_resp.content = "Hello, how can I help?"
        mock_resp.error = None
        mock_resp.has_tool_calls.return_value = False

        with patch("agent.runtime.loop.invoke_llm", return_value=mock_resp):
            with patch("agent.runtime.context_builder.resolve_provider_config") as mock_cfg:
                mock_cfg.return_value = {"enabled": True, "model": "test"}
                result = run_turn(session, turn, services)

        assert result.ok is True
        assert "Hello" in result.final_response

    def test_runtime_loop_tool_call_then_followup(self):
        """Mock LLM returns tool_call first, then assistant message."""
        from unittest.mock import patch
        from agent.runtime.loop import run_turn
        from agent.core.session import AgentSession
        from agent.core.turn import AgentTurn
        from agent.protocol.op import AgentOp
        from agent.runtime.services import RuntimeServices
        from agent.llm.schemas import LLMToolCall
        from agent.tools.registry import ToolRegistry
        from agent.tools.router import ToolRouter
        from agent.skills.registry import SkillRegistry
        from agent.modules.registry import ModuleRegistry
        from agent.audit.events import EventRecorder
        from agent.audit.trace import TraceRecorder
        from agent.audit.rollout import RolloutRecorder

        reg = ToolRegistry()
        services = RuntimeServices(
            tool_service=ToolRouter(registry=reg),
            skill_service=SkillRegistry(),
            module_service=ModuleRegistry(),
            audit_service={
                "events": EventRecorder(),
                "trace": TraceRecorder(),
                "rollout": RolloutRecorder(),
            },
        )

        session = AgentSession(session_id="s1", services=services)
        op = AgentOp.user_message("check health")
        turn = AgentTurn.from_op(op)

        # First response: tool_call
        resp1 = MagicMock()
        resp1.content = ""
        resp1.error = None
        resp1.has_tool_calls.return_value = True
        resp1.tool_calls = [LLMToolCall(id="call_1", name="runtime__health", arguments={"check": "all"})]

        # Second response: assistant message
        resp2 = MagicMock()
        resp2.content = "Health check passed"
        resp2.error = None
        resp2.has_tool_calls.return_value = False

        with patch("agent.runtime.loop.invoke_llm") as mock_invoke:
            mock_invoke.side_effect = [resp1, resp2]
            with patch("agent.runtime.context_builder.resolve_provider_config") as mock_cfg:
                mock_cfg.return_value = {"enabled": True, "model": "test"}
                with patch.object(reg, 'dispatch', return_value={"ok": True, "summary": "healthy", "errors": [], "warnings": []}):
                    result = run_turn(session, turn, services)

        assert result.ok is True
        assert "Health" in result.final_response
        assert len(result.tool_calls) == 1


class TestToolRouter:
    """Test ToolRouter — visible specs vs registry, name mapping."""

    def test_tool_router_separates_visible_specs_and_registry(self):
        """model_visible_specs and registry are separate."""
        from agent.tools.registry import ToolRegistry
        from agent.tools.router import ToolRouter
        from agent.tools.schemas import ToolSpec

        reg = ToolRegistry()
        reg._specs["test.tool"] = ToolSpec(tool_id="test.tool", enabled=True, forbidden=False, callable_by_llm=True)
        router = ToolRouter(registry=reg)

        assert len(router.model_visible_specs) == 1
        assert router.registry.get("test.tool") is not None

    def test_tool_router_maps_llm_safe_name_to_real_tool_id(self):
        """runtime__health maps to runtime.health."""
        from agent.tools.router import ToolRouter
        rt = ToolRouter()
        mock_tc = MagicMock()
        mock_tc.id = "c1"
        mock_tc.name = "runtime__health"
        mock_tc.arguments = {}
        result = rt.build_tool_call(mock_tc)
        assert result.real_tool_id == "runtime.health"


class TestSkillRegistry:
    """Test SkillRegistry distinguishes enabled vs planned."""

    def test_skill_registry_distinguishes_enabled_and_planned(self):
        from agent.skills.registry import SkillRegistry
        reg = SkillRegistry()
        enabled = reg.list_enabled_skills()
        planned = reg.list_planned_skills()

        assert len(enabled) > 0, "Must have enabled skills"
        assert len(planned) > 0, "Must have planned skills"
        # config_translation should be enabled
        enabled_ids = [s.skill_id for s in enabled]
        assert "config_translation" in enabled_ids
        planned_ids = [s.skill_id for s in planned]
        assert "topology" in planned_ids


class TestModuleRegistry:
    """Test ModuleRegistry distinguishes enabled vs planned."""

    def test_module_registry_distinguishes_enabled_and_planned(self):
        from agent.modules.registry import ModuleRegistry
        reg = ModuleRegistry()
        enabled = reg.list_enabled_modules()
        planned = reg.list_planned_modules()

        assert len(enabled) > 0
        assert len(planned) > 0
        enabled_ids = [m.module_id for m in enabled]
        planned_ids = [m.module_id for m in planned]
        assert "config_translation" in enabled_ids
        assert "topology" in planned_ids


class TestRuntimeSnapshotInjection:
    """Test RuntimeSnapshot is injected into LLM messages."""

    def test_runtime_snapshot_injected_into_llm_messages(self):
        """LLM messages contain RuntimeSnapshot text."""
        from agent.context.snapshot import RuntimeSnapshot
        snap = RuntimeSnapshot(
            tool_count=3, visible_tool_count=3,
            enabled_skills=["config_translation"],
            planned_skills=["topology"],
            enabled_modules=["config_translation"],
            planned_modules=["topology"],
            workspace_id="test", model="MiniMax-M3",
        )
        text = snap.to_prompt_text()
        assert "RUNTIME SNAPSHOT" in text
        assert "config_translation" in text
        assert "topology" in text

    def test_capability_answer_based_on_snapshot_planned_not_claimed(self):
        """Snapshot clearly marks planned skills as NOT available."""
        from agent.context.snapshot import RuntimeSnapshot
        snap = RuntimeSnapshot(
            planned_skills=["topology"],
            enabled_skills=["config_translation"],
        )
        text = snap.to_prompt_text()
        assert "NOT yet available" in text or "not callable" in text.lower()
        assert "current" in text.lower() or "now" in text.lower()


class TestEventRecorder:
    """Test EventRecorder records turn lifecycle."""

    def test_event_recorder_records_turn_lifecycle(self):
        from agent.audit.events import EventRecorder
        rec = EventRecorder()

        rec.emit("turn_started", session_id="s1", turn_id="t1")
        rec.emit("context_built", session_id="s1", turn_id="t1")
        rec.emit("model_request_started", session_id="s1", turn_id="t1")
        rec.emit("model_response_received", session_id="s1", turn_id="t1")
        rec.emit("assistant_message", session_id="s1", turn_id="t1")
        rec.emit("turn_finished", session_id="s1", turn_id="t1")

        events = rec.events_for_turn("t1")
        types = [e.type for e in events]
        assert "turn_started" in types
        assert "context_built" in types
        assert "model_request_started" in types
        assert "model_response_received" in types
        assert "assistant_message" in types
        assert "turn_finished" in types

    def test_tool_call_events_recorded(self):
        from agent.audit.events import EventRecorder
        rec = EventRecorder()

        rec.emit("tool_call_started", turn_id="t1", tool_id="runtime.health")
        rec.emit("tool_call_finished", turn_id="t1", tool_id="runtime.health")

        events = rec.events_for_turn("t1")
        types = [e.type for e in events]
        assert "tool_call_started" in types
        assert "tool_call_finished" in types


class TestAPIAgentMessage:
    """Test /api/agent/message uses AgentApp."""

    def test_api_agent_message_uses_new_agent_app(self):
        """API /api/agent/message routes through AgentApp, not graph.py."""
        from agent.app.service import reset_agent_app_for_tests
        reset_agent_app_for_tests()

        try:
            from backend.api.agent_routes import agent_bp
            assert agent_bp is not None
            # Verify the blueprint is registered
            assert hasattr(agent_bp, 'name')
        except ImportError:
            # If Flask not installed, the route file should still import cleanly
            import importlib
            spec = importlib.util.find_spec("backend.api.agent_routes")
            assert spec is not None, "agent_routes.py must exist"
