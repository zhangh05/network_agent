# harness/test_llm_high_privilege_invocation_v052.py
"""LLM Runtime v0.5.2 — high-privilege invocation reliability tests.

Tests:
1. invoke_llm passes safe_context to provider
2. safe_generate disabled metadata consistency
3. composer returns LLM answer even when safe_to_show=False
4. non-chat composer returns LLM answer even when safe_to_show=False
5. health HTTP 400 not connected
6. assistant_chat still invokes with tools
7. tool call safe name maps to real tool_id
"""

import pytest
from unittest.mock import MagicMock, patch


class TestInvokeLLMPassesSafeContext:
    """Fix 1: invoke_llm() must pass safe_context to LLMRequest → provider.generate."""

    def test_invoke_llm_passes_safe_context_to_provider(self):
        """provider.generate must receive req.safe_context from invoke_llm."""
        from agent.llm.schemas import LLMResponse, LLMMessage

        safe_ctx_value = {}

        def capture_req(req):
            safe_ctx_value["received"] = req.safe_context
            safe_ctx_value["mock_type"] = req.safe_context.get("_mock_response_type", "none")
            return LLMResponse(content="ok", provider="mock", model="mock")

        with patch("agent.llm.config.resolve_provider_config") as mock_cfg:
            mock_cfg.return_value = {
                "enabled": True,
                "provider_type": "openai_compatible",
                "provider": "minimax",
                "model": "MiniMax-M3",
                "api_key": "sk-test",
                "base_url": "https://api.test/v1",
                "temperature": 0.2,
                "max_tokens": 4096,
            }
            with patch("agent.llm.runtime._build_prompt_messages") as mock_msgs:
                mock_msgs.return_value = [LLMMessage(role="user", content="test")]
                with patch("agent.llm.provider.generate", side_effect=capture_req):
                    from agent.llm.runtime import invoke_llm
                    invoke_llm(
                        "result_summarize",
                        safe_context={"_mock_response_type": "unsafe"},
                    )

                    assert safe_ctx_value["mock_type"] == "unsafe", \
                        f"safe_context not passed through: {safe_ctx_value}"


class TestSafeGenerateDisabledMetadata:
    """Fix 2: safe_generate() disabled branch metadata must match invoke_llm()."""

    def test_safe_generate_disabled_metadata_consistent(self):
        """safe_generate() with disabled config → metadata has disabled_by_user."""
        from agent.llm.schemas import LLMResponse, LLMMessage

        with patch("agent.llm.config.resolve_provider_config") as mock_cfg:
            mock_cfg.return_value = {
                "enabled": False,
                "provider_type": "disabled",
                "provider": "disabled",
            }
            from agent.llm.runtime import safe_generate
            output = safe_generate("result_summarize", user_input="test")

            assert output.llm_used is False
            assert output.metadata["provider_error_type"] == "disabled_by_user"
            assert output.metadata["http_status"] is None
            assert output.fallback_reason is not None
            assert len(output.fallback_reason) > 0


class TestComposerReturnsLLMAnswerSafeToShowFalse:
    """Fix 3: composer must return LLM answer even when safe_to_show=False."""

    def test_composer_returns_llm_answer_even_when_safe_to_show_false(self):
        """_compose_assistant_chat: safe_to_show=False but answer still used."""
        from agent.llm.schemas import SafeLLMOutput
        from unittest.mock import patch

        output = SafeLLMOutput(
            answer="LLM unsafe-but-returned answer",
            llm_used=True,
            safe_to_show=False,
            warnings=["response_policy_warning"],
        )

        with patch("agent.nodes.composer._resolve_and_update_llm") as mock_cfg:
            mock_cfg.return_value = {
                "enabled": True,
                "provider_type": "openai_compatible",
                "provider": "minimax",
                "model": "MiniMax-M3",
            }
            with patch("agent.llm.runtime.safe_generate", return_value=output):
                from agent.state import NetworkAgentState
                from agent.legacy.composer import _compose_assistant_chat

                state = NetworkAgentState()
                state.user_input = "test"
                state.intent = "assistant_chat"
                state.context = {"llm": {}}
                state.warnings = []
                state.final_response = ""
                state.skill_results = {}
                state.tool_results = {}

                _compose_assistant_chat(state)
                # _compose_assistant_chat modifies state in place (does not return)

                assert state.final_response == "LLM unsafe-but-returned answer"
                assert len(state.warnings) > 0
                assert state.context["llm"]["safe_to_show"] is False
                assert state.context["llm"]["fallback"] is False

    def test_non_chat_composer_returns_llm_answer_even_when_safe_to_show_false(self):
        """compose() non-chat path: safe_to_show=False but answer still used."""
        from agent.llm.schemas import SafeLLMOutput
        from unittest.mock import patch, MagicMock

        output = SafeLLMOutput(
            answer="LLM result even unsafe",
            llm_used=True,
            safe_to_show=False,
            warnings=["warn1"],
        )

        with patch("agent.llm.runtime.safe_generate", return_value=output):
            from agent.state import NetworkAgentState
            from agent.legacy.composer import compose

            state = NetworkAgentState()
            state.user_input = "summarize result"
            state.intent = "result_summarize"
            state.context = {
                "llm": {},
                "execution": {},
                "routing": {},
            }
            state.warnings = []
            state.final_response = ""
            state.skill_results = {}

            result = compose(state)

            # Answer should be returned (not hidden)
            assert result.final_response == "LLM result even unsafe"
            # safe_to_show should be recorded
            assert result.context["llm"].get("safe_to_show") is False


class TestHealthHTTP400NotConnected:
    """Fix 4: provider health must not set connected=true on HTTP 400."""

    def test_health_http_400_not_connected(self):
        """health() HTTP 400 → chat_completion_endpoint_reachable=True, connected=False."""
        from unittest.mock import patch, MagicMock
        from agent.llm.provider import health

        with patch("agent.llm.config.resolve_provider_config") as mock_cfg:
            mock_cfg.return_value = {
                "enabled": True,
                "provider_type": "openai_compatible",
                "provider": "minimax",
                "api_key": "sk-fake",
                "base_url": "https://api.test/v1",
                "model": "MiniMax-M3",
            }
            # Mock all network calls to succeed for base_url and models,
            # but fail with 400 for chat/completions
            import urllib.error
            http_400 = urllib.error.HTTPError(
                "https://api.test/v1/chat/completions",
                400,
                "Bad Request",
                {},
                MagicMock(read=MagicMock(return_value=b'{"error":{"message":"invalid model"}}', decode=MagicMock(return_value='{"error":{"message":"invalid model"}}'))),
            )

            with patch("urllib.request.urlopen") as mock_urlopen:
                # Call 1: base_url HEAD (success)
                # Call 2: /models (success)
                # Call 3: /chat/completions (fail with 400)

                mock_200 = MagicMock()
                mock_200.status = 200
                mock_200.__enter__ = MagicMock(return_value=mock_200)
                mock_200.__exit__ = MagicMock(return_value=False)

                def side_effect(*args, **kwargs):
                    req = args[0]
                    url = req.get_full_url() if hasattr(req, 'get_full_url') else str(req)
                    if "/chat/completions" in url:
                        raise http_400
                    return mock_200

                mock_urlopen.side_effect = side_effect
                mock_urlopen.__enter__ = MagicMock(return_value=mock_200)
                mock_urlopen.__exit__ = MagicMock(return_value=False)

                result = health()

                assert result["chat_completion_endpoint_reachable"] is True, \
                    f"Expected chat_completion_endpoint_reachable=True, got {result}"
                assert result["chat_completion_ok"] is False
                assert result["connected"] is False
                assert result["http_status"] == 400


class TestAssistantChatKeepsWithTools:
    """Fix 5: assistant_chat must remain default with-tools."""

    def test_assistant_chat_still_invokes_with_tools(self):
        """assistant_chat calls invoke_llm with tools (not empty)."""
        from unittest.mock import MagicMock, patch

        captured_tools = {}

        def capture_invoke(task, messages=None, tools=None, **kwargs):
            captured_tools["task"] = task
            captured_tools["tools"] = tools
            mock_resp = MagicMock()
            mock_resp.error = None
            mock_resp.has_tool_calls = MagicMock(return_value=False)
            mock_resp.content = "LLM response"
            return mock_resp

        with patch("agent.llm.config.resolve_provider_config") as mock_cfg:
            mock_cfg.return_value = {
                "enabled": True,
                "provider_type": "openai_compatible",
                "provider": "minimax",
                "model": "MiniMax-M3",
                "api_key": "sk-test",
                "base_url": "https://api.test/v1",
                "temperature": 0.2,
                "max_tokens": 4096,
            }
            with patch("agent.llm.runtime.invoke_llm", side_effect=capture_invoke):
                from agent.state import NetworkAgentState
                from agent.legacy.llm_orchestrator import orchestrate

                state = NetworkAgentState()
                state.user_input = "help"
                state.intent = "assistant_chat"
                state.context = {}
                state.warnings = []

                result = orchestrate(state)

                assert captured_tools["task"] == "assistant_chat"
                assert captured_tools["tools"] is not None
                assert len(captured_tools["tools"]) > 0, "assistant_chat must invoke with tools"

    def test_tool_call_safe_name_maps_to_real_tool_id(self):
        """LLM returns runtime__health → orchestrator executes runtime.health."""
        from unittest.mock import MagicMock, patch
        from agent.llm.schemas import LLMToolCall

        captured_tool_id = {}

        def fake_execute(tool_id, args, ws_id=None, state=None):
            captured_tool_id["executed"] = tool_id
            return {"status": "ok", "result": "health ok", "ok": True, "summary": "ok", "errors": [], "warnings": []}

        # LLM response with LLM-safe name
        mock_resp = MagicMock()
        mock_resp.error = None
        mock_resp.has_tool_calls = MagicMock(return_value=True)
        mock_resp.tool_calls = [
            LLMToolCall(id="call_1", name="runtime__health", arguments={"check": "all"})
        ]

        with patch("agent.llm.config.resolve_provider_config") as mock_cfg:
            mock_cfg.return_value = {
                "enabled": True,
                "provider_type": "openai_compatible",
                "provider": "minimax",
                "model": "MiniMax-M3",
                "api_key": "sk-test",
                "base_url": "https://api.test/v1",
                "temperature": 0.2,
                "max_tokens": 4096,
            }
            with patch("agent.nodes.llm_orchestrator._execute_tool", side_effect=fake_execute):
                with patch("agent.llm.runtime.invoke_llm", return_value=mock_resp):
                    from agent.state import NetworkAgentState
                    from agent.legacy.llm_orchestrator import orchestrate

                    state = NetworkAgentState()
                    state.user_input = "check health"
                    state.context = {}
                    state.warnings = []

                    result = orchestrate(state)

                    # Tool should be executed with REAL tool_id (not LLM-safe name)
                    assert captured_tool_id["executed"] == "runtime.health", \
                        f"Expected runtime.health, got {captured_tool_id.get('executed')}"
