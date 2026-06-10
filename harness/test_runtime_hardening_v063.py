"""Agent Backend v0.6.3 — Runtime Hardening & ToolRouter Correctness Tests.

Tests:
P0-1: default_runtime_services builds real ToolRouter
P0-2: ToolRouter whitelist validation
P0-3: tool dispatch exception events
P1-1: RuntimeSnapshot tool_count vs visible_tool_count
P1-2: System prompt Runtime Contract
P1-3: max_steps AgentResult metadata
"""

import os
import json
import pytest
from unittest.mock import patch, MagicMock

os.environ.setdefault("RATE_LIMIT_DISABLED", "1")


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_DISABLED", "1")


# ═══════════════════════════════════════════════════════════════════════
# P0-1: default_runtime_services ToolRouter
# ═══════════════════════════════════════════════════════════════════════

class TestDefaultRuntimeServices:
    """default_runtime_services must build real ToolRouter from catalog."""

    def test_default_runtime_services_builds_real_tool_router(self):
        """default_runtime_services().tool_service must be ToolRouter."""
        from agent.runtime.services import default_runtime_services
        from agent.tools.router import ToolRouter
        svc = default_runtime_services()
        assert svc.tool_service is not None
        assert isinstance(svc.tool_service, ToolRouter), \
            f"Expected ToolRouter, got {type(svc.tool_service)}"

    def test_default_tool_router_has_non_empty_registry(self):
        """ToolRouter registry must have tools > 0."""
        from agent.runtime.services import default_runtime_services
        svc = default_runtime_services()
        router = svc.tool_service
        assert router.registry is not None
        all_tools = router.registry.list_all()
        assert len(all_tools) > 0, "Registry should have tools"

    def test_model_visible_tools_non_empty(self):
        """model_visible_tools() must return tools."""
        from agent.runtime.services import default_runtime_services
        svc = default_runtime_services()
        visible = svc.tool_service.model_visible_tools()
        assert len(visible) > 0, "Should have model-visible tools"

    def test_tool_count_ge_visible_tool_count(self):
        """registry.list_all count >= model_visible_tools count."""
        from agent.runtime.services import default_runtime_services
        svc = default_runtime_services()
        all_count = len(svc.tool_service.registry.list_all())
        visible_count = len(svc.tool_service.model_visible_tools())
        assert all_count >= visible_count, \
            f"all={all_count} < visible={visible_count}"

    def test_forbidden_tools_not_model_visible(self):
        """Forbidden tools must NOT appear in model_visible_tools."""
        from agent.runtime.services import default_runtime_services
        svc = default_runtime_services()
        router = svc.tool_service
        # Check that forbidden tools are not visible
        all_tools = router.registry.list_all()
        visible_specs = router.model_visible_specs
        visible_ids = {s.real_tool_id for s in visible_specs}
        for t in all_tools:
            if t.forbidden:
                assert t.tool_id not in visible_ids, \
                    f"Forbidden tool {t.tool_id} is model-visible!"


# ═══════════════════════════════════════════════════════════════════════
# P0-2: ToolRouter whitelist validation
# ═══════════════════════════════════════════════════════════════════════

class TestToolRouterWhitelist:
    """ToolRouter.build_tool_call must validate against llm_name_map."""

    @pytest.fixture
    def router_with_tool(self):
        from agent.tools.router import ToolRouter
        from agent.tools.registry import ToolRegistry
        from agent.tools.schemas import ToolSpec
        reg = ToolRegistry()
        spec = ToolSpec(
            tool_id="test.hello",
            name="test.hello",
            category="test",
            description="A test tool",
            risk_level="low",
            enabled=True,
            callable_by_llm=True,
            input_schema={},
        )
        reg._specs["test.hello"] = spec
        return ToolRouter(registry=reg)

    def test_tool_router_uses_llm_name_map(self, router_with_tool):
        """Visible tools must be in llm_name_map."""
        router = router_with_tool
        # The tool should be in the name map
        safe_name = "test__hello"  # llm-name from to_llm_tool_name
        assert len(router.llm_name_map) > 0, "llm_name_map should not be empty"
        assert any("test" in k for k in router.llm_name_map.keys()), \
            "test tool should be in llm_name_map"

    def test_tool_router_rejects_unknown_llm_tool_name(self, router_with_tool):
        """Unknown tool name must raise UnknownToolCallError."""
        from agent.tools.router import UnknownToolCallError
        router = router_with_tool
        fake_call = MagicMock()
        fake_call.name = "nonexistent_tool"
        fake_call.id = "call_1"
        fake_call.arguments = {}
        with pytest.raises(UnknownToolCallError):
            router.build_tool_call(fake_call)

    def test_visible_tool_builds_correctly(self, router_with_tool):
        """Known visible tool builds successfully."""
        router = router_with_tool
        visible = router.model_visible_specs
        if visible:
            first_spec = visible[0]
            fake_call = MagicMock()
            fake_call.name = first_spec.name
            fake_call.id = "call_1"
            fake_call.arguments = {}
            tc = router.build_tool_call(fake_call)
            assert tc.real_tool_id == first_spec.real_tool_id


# ═══════════════════════════════════════════════════════════════════════
# P0-3: tool dispatch exception events
# ═══════════════════════════════════════════════════════════════════════

class TestToolDispatchExceptionEvents:
    """Dispatch exceptions must record tool_call_failed + trace."""

    def test_dispatch_exception_records_tool_call_failed(self):
        """dispatch exception must emit tool_call_failed event."""
        from agent.app.service import get_default_agent_app, reset_agent_app_for_tests
        reset_agent_app_for_tests()
        app = get_default_agent_app()

        # Mock: first turn LLM returns tool_call, then dispatch raises
        from agent.llm.schemas import LLMResponse
        fake_tc = type('FakeTC', (), {
            'id': 'call_e1',
            'name': 'runtime__health',
            'arguments': {},
        })()

        responses = [
            LLMResponse(tool_calls=[fake_tc]),
            LLMResponse(content="Recovered after tool error."),
        ]

        with patch("agent.runtime.loop.invoke_llm") as mock_llm:
            mock_llm.side_effect = responses
            with patch.object(app.services.tool_service, 'dispatch', side_effect=RuntimeError("simulated crash")):
                result = app.submit_user_message(
                    user_input="test dispatch exception",
                    session_id="dispatch-test",
                )

        assert result is not None
        assert result.ok is True  # should recover via LLM follow-up
        # Check events
        event_types = [e["type"] for e in result.events]
        assert "tool_call_started" in event_types, f"Expected tool_call_started, got {event_types}"
        assert "tool_call_failed" in event_types, f"Expected tool_call_failed, got {event_types}"

    def test_dispatch_exception_does_not_crash_turn(self):
        """Dispatch exception must not crash the entire turn."""
        from agent.app.service import get_default_agent_app, reset_agent_app_for_tests
        from agent.llm.schemas import LLMResponse
        reset_agent_app_for_tests()
        app = get_default_agent_app()

        fake_tc = type('FakeTC', (), {
            'id': 'call_crash',
            'name': 'runtime__health',
            'arguments': {},
        })()

        responses = [
            LLMResponse(tool_calls=[fake_tc]),
            LLMResponse(content="I encountered an error but recovered."),
        ]

        with patch("agent.runtime.loop.invoke_llm") as mock_llm:
            mock_llm.side_effect = responses
            with patch.object(app.services.tool_service, 'dispatch', side_effect=RuntimeError("boom")):
                result = app.submit_user_message(
                    user_input="please crash",
                    session_id="crash-test",
                )

        assert result is not None
        assert result.ok is True  # Turn recovered
        assert len(result.tool_calls) > 0, "Should have tool call records"

    def test_unknown_tool_call_recorded_and_fed_back(self):
        """Unknown tool call must be recorded and fed back to LLM."""
        from agent.app.service import get_default_agent_app, reset_agent_app_for_tests
        from agent.llm.schemas import LLMResponse
        reset_agent_app_for_tests()
        app = get_default_agent_app()

        # LLM tries to call a tool that's not in llm_name_map
        fake_tc = type('FakeTC', (), {
            'id': 'call_unknown',
            'name': 'ssh__exec',
            'arguments': {},
        })()

        responses = [
            LLMResponse(tool_calls=[fake_tc]),
            LLMResponse(content="Sorry, I don't have that tool. How else can I help?"),
        ]

        with patch("agent.runtime.loop.invoke_llm") as mock_llm:
            mock_llm.side_effect = responses
            result = app.submit_user_message(
                user_input="ssh to device",
                session_id="unknown-tool-test",
            )

        assert result is not None
        assert result.ok is True
        event_types = [e["type"] for e in result.events]
        # Should have tool_call_failed for the unknown tool
        assert "tool_call_failed" in event_types


# ═══════════════════════════════════════════════════════════════════════
# P1-1: RuntimeSnapshot tool_count vs visible_tool_count
# ═══════════════════════════════════════════════════════════════════════

class TestRuntimeSnapshotCounts:
    """RuntimeSnapshot must distinguish total tool_count vs visible_tool_count."""

    def test_snapshot_tool_count_distinguishes_total_and_visible(self):
        """tool_count = all tools, visible_tool_count = model-visible only."""
        from agent.context.snapshot import RuntimeSnapshot
        snap = RuntimeSnapshot(
            tool_count=55,
            visible_tool_count=40,
            enabled_skills=["assistant_chat"],
            planned_skills=["topology"],
            enabled_modules=["config_translation"],
            planned_modules=["inspection"],
        )
        text = snap.to_prompt_text()
        assert "55" in text, f"Should mention total tool count (55), got:\n{text}"
        assert "40" in text, f"Should mention visible tool count (40), got:\n{text}"

    def test_to_prompt_text_sections(self):
        """to_prompt_text must have Current Tools, Enabled Skills sections."""
        from agent.context.snapshot import RuntimeSnapshot
        snap = RuntimeSnapshot(
            tool_count=55,
            visible_tool_count=40,
            enabled_skills=["assistant_chat", "config_translation"],
            planned_skills=["topology"],
            enabled_modules=["config_translation"],
            planned_modules=["inspection", "cmdb"],
        )
        text = snap.to_prompt_text()
        assert "Current Tools" in text
        assert "55" in text or "total" in text.lower()
        assert "Enabled Skills:" in text
        assert "Planned Skills" in text and "NOT yet available" in text
        assert "not callable" in text

    def test_planned_not_in_enabled(self):
        """Planned skills/modules must be in planned section, not enabled."""
        from agent.context.snapshot import RuntimeSnapshot
        snap = RuntimeSnapshot(
            enabled_skills=["assistant_chat"],
            planned_skills=["topology", "cmdb"],
            enabled_modules=["config_translation"],
            planned_modules=["inspection"],
        )
        text = snap.to_prompt_text()
        # enabled section should NOT mention planned items
        enabled_section_start = text.find("Enabled Skills:")
        planned_section_start = text.find("Planned Skills")
        if planned_section_start > 0:
            enabled_section = text[enabled_section_start:planned_section_start]
            assert "topology" not in enabled_section, "Planned should not be in enabled section"


# ═══════════════════════════════════════════════════════════════════════
# P1-2: System prompt Runtime Contract
# ═══════════════════════════════════════════════════════════════════════

class TestSystemPromptContract:
    """System prompt must contain Runtime Contract clauses."""

    def test_system_prompt_contains_runtime_contract(self):
        """System prompt must have Runtime Contract header."""
        from agent.runtime.prompts import build_system_prompt
        prompt = build_system_prompt()
        assert "Runtime Contract" in prompt
        assert "Network Agent" in prompt

    def test_system_prompt_says_planned_not_callable(self):
        """System prompt must state planned skills/modules NOT callable."""
        from agent.runtime.prompts import build_system_prompt
        prompt = build_system_prompt()
        assert "NOT callable" in prompt or "not callable" in prompt.lower()

    def test_system_prompt_restricts_tools_to_model_visible(self):
        """System prompt must require only calling model-visible tools."""
        from agent.runtime.prompts import build_system_prompt
        prompt = build_system_prompt()
        assert "model-visible" in prompt or "Only call" in prompt

    def test_system_prompt_prevents_deployable_config(self):
        """System prompt must forbid LLM from generating deployable_config."""
        from agent.runtime.prompts import build_system_prompt
        prompt = build_system_prompt()
        assert "deployable_config" in prompt

    def test_system_prompt_mentions_knowledge_base(self):
        """System prompt must address knowledge base availability."""
        from agent.runtime.prompts import build_system_prompt
        prompt = build_system_prompt()
        assert "knowledge" in prompt.lower()


# ═══════════════════════════════════════════════════════════════════════
# P1-3: max_steps AgentResult metadata
# ═══════════════════════════════════════════════════════════════════════

class TestMaxStepsMetadata:
    """max_steps exceeded must produce proper metadata."""

    def test_max_steps_result_contains_partial_metadata(self):
        """max_steps AgentResult must have terminal_reason + partial."""
        from agent.app.service import get_default_agent_app, reset_agent_app_for_tests
        from agent.llm.schemas import LLMResponse
        reset_agent_app_for_tests()
        app = get_default_agent_app()

        # Create responses that keep calling tools forever
        fake_tc = type('FakeTC', (), {
            'id': 'call_loop',
            'name': 'runtime__health',
            'arguments': {},
        })()

        responses = [LLMResponse(tool_calls=[fake_tc]) for _ in range(10)]

        with patch("agent.runtime.loop.invoke_llm") as mock_llm:
            mock_llm.side_effect = responses
            result = app.submit_user_message(
                user_input="loop forever",
                session_id="max-steps-test",
            )

        assert result is not None
        assert result.ok is True
        assert "max_steps" in str(result.warnings).lower()
        assert result.metadata.get("terminal_reason") == "max_steps_exceeded"
        assert result.metadata.get("partial") is True
        assert "steps" in result.metadata
