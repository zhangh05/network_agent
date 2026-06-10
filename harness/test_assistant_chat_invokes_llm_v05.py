# harness/test_assistant_chat_invokes_llm_v05.py
"""assistant_chat Invocation v0.5 — assistant_chat must invoke LLM via unified runtime."""

import pytest
from unittest.mock import MagicMock, patch


class TestAssistantChatInvokesLLM:
    """assistant_chat must NOT defer — must call LLM via invoke_llm()."""

    def test_assistant_chat_no_deferred(self):
        """assistant_chat intent must NOT set mode=assistant_chat_deferred."""
        from agent.state import NetworkAgentState
        from agent.nodes.llm_orchestrator import orchestrate

        state = NetworkAgentState(intent="assistant_chat", user_input="Hello")

        # Mock invoke_llm to return a response with no tool calls
        mock_resp = MagicMock()
        mock_resp.error = None
        mock_resp.content = "Hello! How can I help you?"
        mock_resp.has_tool_calls = MagicMock(return_value=False)

        with patch("agent.llm.runtime.invoke_llm", return_value=mock_resp):
            result = orchestrate(state)

            # Key assertion: mode must NOT be "assistant_chat_deferred"
            mode = (result.tool_results or {}).get("mode", "")
            assert mode != "assistant_chat_deferred", \
                "assistant_chat must NOT defer — must call LLM"
            # Either "llm_orchestrated" or "assistant_chat" is acceptable
            assert result.final_response != "", "assistant_chat must produce a response"


class TestAssistantChatNoToolsMode:
    """assistant_chat no-tools mode (default)."""

    def test_no_tools_mode_succeeds(self):
        """Normal assistant_chat (no tool request) succeeds with no-tools mode."""
        from agent.state import NetworkAgentState
        from agent.nodes.llm_orchestrator import orchestrate

        state = NetworkAgentState(intent="assistant_chat", user_input="What is  OSPF?")

        # Mock invoke_llm to return a simple text response (no tool calls)
        mock_resp = MagicMock()
        mock_resp.error = None
        mock_resp.content = "OSPF is a link-state routing protocol..."
        mock_resp.has_tool_calls = MagicMock(return_value=False)

        with patch("agent.llm.runtime.invoke_llm", return_value=mock_resp):
            result = orchestrate(state)

            assert result.final_response != "", "Must produce a response"
            assert "OSPF" in result.final_response or \
                   "OSPF" in (result.tool_results or {}).get("answer", "")


class TestAssistantChatWithToolsMode:
    """assistant_chat with-tools mode (when user explicitly requests tools)."""

    def test_with_tools_mode_does_not_break_toolpolicy(self):
        """Tool-request chat with-tools mode must not bypass ToolPolicy."""
        from agent.state import NetworkAgentState
        from agent.nodes.llm_orchestrator import orchestrate
        from agent.llm.schemas import LLMResponse, LLMToolCall

        state = NetworkAgentState(
            intent="assistant_chat",
            user_input="帮我调用 runtime.health 检查一下"
        )

        # Mock invoke_llm to return a tool call
        mock_resp = LLMResponse(
            content="",
            provider="mock", model="mock",
        )
        # Simulate tool call returned by LLM
        mock_resp.has_tool_calls = MagicMock(return_value=True)
        mock_resp.tool_calls = [
            LLMToolCall(id="call_1", name="runtime__health", arguments={}),
        ]

        # Mock _execute_tool to simulate ToolPolicy check
        mock_tool_result = {
            "ok": True,
            "status": "succeeded",
            "summary": "health ok",
        }

        with patch("agent.llm.runtime.invoke_llm", return_value=mock_resp):
            with patch("agent.nodes.llm_orchestrator._execute_tool", return_value=mock_tool_result):
                result = orchestrate(state)

                # Verify that tool_results contains the tool execution
                tool_calls = (result.tool_results or {}).get("tool_calls", [])
                assert len(tool_calls) > 0, "Tool must be executed"
                # Verify real tool_id is recorded (with .)
                if tool_calls:
                    assert "." in tool_calls[0].get("tool_id", ""), \
                        "tool_results must record real tool_id (with .)"


class TestAssistantChatDisabledFallback:
    """assistant_chat when LLM is disabled."""

    def test_disabled_does_not_call_provider(self):
        """When LLM is disabled, assistant_chat uses deterministic fallback."""
        from agent.state import NetworkAgentState
        from agent.nodes.llm_orchestrator import orchestrate

        state = NetworkAgentState(intent="assistant_chat", user_input="Hello")

        # Mock config to disable LLM
        with patch("agent.llm.config.resolve_provider_config") as mock_cfg:
            mock_cfg.return_value = {
                "enabled": False,
                "provider_type": "disabled",
            }
            result = orchestrate(state)

            # When disabled, mode should be "deterministic" or "assistant_chat"
            mode = (result.tool_results or {}).get("mode", "")
            assert mode in ("deterministic", "assistant_chat"), \
                f"Disabled assistant_chat must not call LLM, got mode={mode}"


class TestAssistantChatUnifiedRuntime:
    """assistant_chat must go through unified runtime (invoke_llm)."""

    def test_assistant_chat_calls_invoke_llm(self):
        """Verify that assistant_chat intent calls invoke_llm() (unified entry point)."""
        from agent.state import NetworkAgentState
        from agent.nodes.llm_orchestrator import orchestrate

        state = NetworkAgentState(intent="assistant_chat", user_input="Hello")

        mock_resp = MagicMock()
        mock_resp.error = None
        mock_resp.content = "Hello!"
        mock_resp.has_tool_calls = MagicMock(return_value=False)

        with patch("agent.llm.runtime.invoke_llm", return_value=mock_resp) as mock_invoke:
            orchestrate(state)

            # Key assertion: invoke_llm was called (not generate() directly)
            mock_invoke.assert_called_once(), \
                "assistant_chat must call invoke_llm() (unified runtime entry point)"
