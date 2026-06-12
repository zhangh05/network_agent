# harness/test_assistant_chat_llm_path_completion.py
"""Test assistant_chat LLM path: safe_generate integration, fallback, metadata.

All tests use monkeypatch on safe_generate — no real LLM key needed.
"""

import sys
import os
from pathlib import Path

NETWORK_AGENT_DIR = Path(__file__).resolve().parent.parent
if str(NETWORK_AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(NETWORK_AGENT_DIR))

import pytest
from agent.state import NetworkAgentState
from agent.llm.schemas import SafeLLMOutput, PolicyDecision


# ── Helpers ──

def make_state(user_input="你好", workspace_id="default"):
    state = NetworkAgentState(user_input=user_input, workspace_id=workspace_id)
    state.intent = "assistant_chat"
    return state


def make_safe_output(answer="LLM generated response", llm_used=True,
                     safe_to_show=True, fallback_reason=None, warnings=None,
                     policy_allowed=True):
    """Build a SafeLLMOutput with controllable fields."""
    pd = PolicyDecision(allowed=policy_allowed, reason="test") if not fallback_reason else None
    return SafeLLMOutput(
        summary=answer, answer=answer,
        llm_used=llm_used, safe_to_show=safe_to_show,
        fallback_reason=fallback_reason,
        warnings=warnings or [],
        policy_decision=pd,
        metadata={"prompt_id": "assistant.chat.v1", "prompt_runtime_used": True},
    )


def _mock_resolve_ui_config(enabled=True, provider_type="minimax"):
    return {
        "enabled": enabled,
        "provider": "minimax",
        "provider_type": provider_type,
        "model": "MiniMax-M3",
        "config_source": "ui_settings",
        "base_url": "https://api.minimaxi.com/v1",
        "key_loaded": True,
        "api_key": "sk-test",
        "enabled_by_ui": True,
        "key_source": "ui_settings",
        "timeout": 30,
        "temperature": 0.2,
        "max_tokens": 1200,
    }


# ── Tests ──


class TestAssistantChatLLMPath:
    """Test _compose_assistant_chat LLM integration path."""

    def test_llm_enabled_calls_safe_generate(self, monkeypatch):
        """LLM enabled & available → safe_generate('assistant_chat') is called."""
        import agent.legacy.composer as mod
        from agent.llm import runtime as llm_runtime
        called = []

        def fake_safe_generate(task, state, **kwargs):
            called.append(task)
            return make_safe_output(answer="Hello from LLM!")

        monkeypatch.setattr(llm_runtime, "safe_generate", fake_safe_generate)
        monkeypatch.setattr("agent.llm.config.resolve_provider_config", _mock_resolve_ui_config)

        state = make_state("你好")
        mod._compose_assistant_chat(state)

        assert called == ["assistant_chat"], f"Expected assistant_chat call, got {called}"
        assert "Hello from LLM!" in (state.final_response or "")

    def test_llm_output_used_in_final_response(self, monkeypatch):
        """safe_generate returns compliant output → final_response uses LLM text."""
        import agent.legacy.composer as mod
        from agent.llm import runtime as llm_runtime

        def fake_safe_generate(task, state, **kwargs):
            return make_safe_output(answer="你好！我是 Network Agent，你可以问我配置翻译相关的问题。")

        monkeypatch.setattr(llm_runtime, "safe_generate", fake_safe_generate)
        monkeypatch.setattr("agent.llm.config.resolve_provider_config", _mock_resolve_ui_config)

        state = make_state("你能做什么？")
        mod._compose_assistant_chat(state)

        assert state.final_response is not None
        assert "Network Agent" in state.final_response
        assert "配置翻译" in state.final_response

    def test_llm_metadata_used_true(self, monkeypatch):
        """llm metadata marks used=True on successful LLM path."""
        import agent.legacy.composer as mod
        from agent.llm import runtime as llm_runtime

        def fake_safe_generate(task, state, **kwargs):
            return make_safe_output(answer="LLM response")

        monkeypatch.setattr(llm_runtime, "safe_generate", fake_safe_generate)
        monkeypatch.setattr("agent.llm.config.resolve_provider_config", _mock_resolve_ui_config)

        state = make_state("你好")
        mod._compose_assistant_chat(state)

        llm = state.context.get("llm", {})
        assert llm.get("used") is True, f"Expected used=True, got {llm}"
        assert llm.get("enabled") is True

    def test_fallback_false_on_success(self, monkeypatch):
        """fallback=False when LLM succeeds."""
        import agent.legacy.composer as mod
        from agent.llm import runtime as llm_runtime

        def fake_safe_generate(task, state, **kwargs):
            return make_safe_output(answer="Success")

        monkeypatch.setattr(llm_runtime, "safe_generate", fake_safe_generate)
        monkeypatch.setattr("agent.llm.config.resolve_provider_config", _mock_resolve_ui_config)

        state = make_state("你好")
        mod._compose_assistant_chat(state)

        llm = state.context.get("llm", {})
        assert llm.get("fallback") is False, f"Expected fallback=False, got {llm.get('fallback')}"

    def test_llm_disabled_falls_back(self, monkeypatch):
        """LLM disabled → does NOT call provider, uses deterministic fallback."""
        import agent.legacy.composer as mod
        from agent.llm import runtime as llm_runtime
        called = []

        def fake_safe_generate(task, state, **kwargs):
            called.append("SHOULD_NOT_BE_CALLED")
            return make_safe_output(answer="Should not appear")

        monkeypatch.setattr(llm_runtime, "safe_generate", fake_safe_generate)
        monkeypatch.setattr("agent.llm.config.resolve_provider_config",
                            lambda **kw: _mock_resolve_ui_config(enabled=False, provider_type="disabled"))

        state = make_state("你好")
        mod._compose_assistant_chat(state)

        assert called == [], "safe_generate should NOT be called when LLM disabled"
        assert state.final_response is not None
        llm = state.context.get("llm", {})
        assert llm.get("fallback") is True
        assert "disabled" in (llm.get("fallback_reason") or "")

    def test_provider_unavailable_falls_back(self, monkeypatch):
        """Provider throws exception → fallback=True with clear reason."""
        import agent.legacy.composer as mod
        from agent.llm import runtime as llm_runtime

        def fake_safe_generate_raises(task, state, **kwargs):
            raise RuntimeError("Connection timeout: MiniMax API unreachable")

        monkeypatch.setattr(llm_runtime, "safe_generate", fake_safe_generate_raises)
        monkeypatch.setattr("agent.llm.config.resolve_provider_config", _mock_resolve_ui_config)

        state = make_state("你好")
        mod._compose_assistant_chat(state)

        assert state.final_response is not None
        llm = state.context.get("llm", {})
        assert llm.get("fallback") is True
        assert "unavailable" in (llm.get("fallback_reason") or "").lower()
        assert "timeout" in (llm.get("fallback_reason") or "").lower()

    def test_safe_generate_exception_falls_back(self, monkeypatch):
        """safe_generate throws ANY exception → fallback=True."""
        import agent.legacy.composer as mod
        from agent.llm import runtime as llm_runtime

        def fake_safe_generate_error(task, state, **kwargs):
            raise ValueError("Some unexpected error")

        monkeypatch.setattr(llm_runtime, "safe_generate", fake_safe_generate_error)
        monkeypatch.setattr("agent.llm.config.resolve_provider_config", _mock_resolve_ui_config)

        state = make_state("你好")
        mod._compose_assistant_chat(state)

        assert state.final_response is not None
        llm = state.context.get("llm", {})
        assert llm.get("fallback") is True
        assert "unavailable" in (llm.get("fallback_reason") or "").lower()

    def test_policy_blocked_falls_back(self, monkeypatch):
        """safe_generate returns blocked output → fallback=True."""
        import agent.legacy.composer as mod
        from agent.llm import runtime as llm_runtime

        def fake_safe_generate_blocked(task, state, **kwargs):
            return make_safe_output(
                answer="Blocked by policy",
                llm_used=False,
                safe_to_show=False,
                fallback_reason="prompt_output_blocked",
                policy_allowed=False,
            )

        monkeypatch.setattr(llm_runtime, "safe_generate", fake_safe_generate_blocked)
        monkeypatch.setattr("agent.llm.config.resolve_provider_config", _mock_resolve_ui_config)

        state = make_state("你好")
        mod._compose_assistant_chat(state)

        assert state.final_response is not None
        llm = state.context.get("llm", {})
        assert llm.get("fallback") is True
        assert "blocked" in (llm.get("fallback_reason") or "")

    def test_fallback_final_response_not_empty(self, monkeypatch):
        """Fallback path always produces non-empty final_response."""
        import agent.legacy.composer as mod
        from agent.llm import runtime as llm_runtime

        monkeypatch.setattr(llm_runtime, "safe_generate",
                            lambda t, s, **kw: (_ for _ in ()).throw(RuntimeError("fail")))
        monkeypatch.setattr("agent.llm.config.resolve_provider_config", _mock_resolve_ui_config)

        state = make_state("你好")
        mod._compose_assistant_chat(state)

        assert state.final_response, "final_response must not be empty in fallback"
        assert len(state.final_response.strip()) > 10

    def test_fallback_reason_clear(self, monkeypatch):
        """Fallback metadata contains a human-readable reason."""
        import agent.legacy.composer as mod
        from agent.llm import runtime as llm_runtime

        monkeypatch.setattr(llm_runtime, "safe_generate",
                            lambda t, s, **kw: (_ for _ in ()).throw(ConnectionError("refused")))
        monkeypatch.setattr("agent.llm.config.resolve_provider_config", _mock_resolve_ui_config)

        state = make_state("你好")
        mod._compose_assistant_chat(state)

        llm = state.context.get("llm", {})
        reason = llm.get("fallback_reason") or ""
        assert len(reason) > 0, "Fallback reason must be non-empty"
        assert "refused" in reason.lower() or "unavailable" in reason.lower()

    def test_no_deployable_config_produced(self, monkeypatch):
        """assistant_chat never produces deployable_config."""
        import agent.legacy.composer as mod
        from agent.llm import runtime as llm_runtime

        def fake_safe_generate(task, state, **kwargs):
            return make_safe_output(answer="Just chatting, no config")

        monkeypatch.setattr(llm_runtime, "safe_generate", fake_safe_generate)
        monkeypatch.setattr("agent.llm.config.resolve_provider_config", _mock_resolve_ui_config)

        state = make_state("你好")
        mod._compose_assistant_chat(state)

        result = state.skill_results or state.tool_results or {}
        assert "deployable_config" not in result or not result.get("deployable_config")

    def test_no_tool_runtime_called(self, monkeypatch):
        """assistant_chat does not call Tool Runtime."""
        import agent.legacy.composer as mod
        from agent.llm import runtime as llm_runtime

        monkeypatch.setattr(llm_runtime, "safe_generate",
                            lambda t, s, **kw: make_safe_output(answer="no tools"))
        monkeypatch.setattr("agent.llm.config.resolve_provider_config", _mock_resolve_ui_config)

        state = make_state("你好")
        mod._compose_assistant_chat(state)

        # Tool Runtime would add tool_calls entries
        assert len(state.skill_calls) == 0
        assert len(state.tool_calls) == 0

    def test_no_fake_job_artifact_report(self, monkeypatch):
        """assistant_chat does not fabricate jobs/artifacts/reports."""
        import agent.legacy.composer as mod
        from agent.llm import runtime as llm_runtime

        monkeypatch.setattr(llm_runtime, "safe_generate",
                            lambda t, s, **kw: make_safe_output(answer="clean"))
        monkeypatch.setattr("agent.llm.config.resolve_provider_config", _mock_resolve_ui_config)

        state = make_state("你好")
        mod._compose_assistant_chat(state)

        assert not state.context.get("output_artifacts")
        assert not state.context.get("report_artifacts")
        assert not state.context.get("job_refs")


# ── Integration: compose() dispatches to _compose_assistant_chat ──

class TestComposeDispatch:
    """Test that compose() correctly routes assistant_chat to _compose_assistant_chat."""

    def test_compose_routes_to_assistant_chat_path(self, monkeypatch):
        """compose() with intent=assistant_chat calls _compose_assistant_chat."""
        import agent.legacy.composer as mod
        dispatched = []

        def fake_compose_assistant_chat(st):
            dispatched.append(True)
            st.final_response = "composed"
            st.context.setdefault("llm", {})["used"] = True

        monkeypatch.setattr(mod, "_compose_assistant_chat", fake_compose_assistant_chat)

        state = make_state("你好")
        mod.compose(state)

        assert dispatched == [True], "compose() did not call _compose_assistant_chat"
        assert state.final_response == "composed"

    def test_compose_does_not_reroute_translate_config(self, monkeypatch):
        """compose() with intent=translate_config does NOT call _compose_assistant_chat."""
        import agent.legacy.composer as mod
        dispatched = []

        def fake_compose_assistant_chat(st):
            dispatched.append("WRONG")

        monkeypatch.setattr(mod, "_compose_assistant_chat", fake_compose_assistant_chat)

        # Monkeypatch resolve_provider_config to disabled so safe_generate isn't called
        monkeypatch.setattr("agent.llm.config.resolve_provider_config",
                            lambda **kw: {"enabled": False, "provider_type": "disabled",
                                          "provider": "disabled", "model": "",
                                          "config_source": "default"})

        state = NetworkAgentState(user_input="hostname R1", workspace_id="default")
        state.intent = "translate_config"
        state.skill_results = {"ok": True, "deployable_config": "sysname R1", "manual_review": [],
                               "quality_summary": {}}
        mod.compose(state)

        assert dispatched == [], "translate_config must NOT route to _compose_assistant_chat"
        assert state.final_response is not None
