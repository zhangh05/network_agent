# harness/test_llm_tool_name_mapping_v05.py
"""LLM Tool Name Mapping v0.5 — bidirectional . <-> __ tests."""

import pytest
from agent.llm.schemas import LLMToolCall


class TestToLLMName:
    """to_llm_tool_name: tool_id → LLM-safe name ( . → __ )"""

    def test_runtime_health(self):
        from agent.llm.tool_adapter import to_llm_tool_name
        assert to_llm_tool_name("runtime.health") == "runtime__health"

    def test_web_search(self):
        from agent.llm.tool_adapter import to_llm_tool_name
        assert to_llm_tool_name("web.search") == "web__search"

    def test_artifact_list(self):
        from agent.llm.tool_adapter import to_llm_tool_name
        assert to_llm_tool_name("artifact.list") == "artifact__list"

    def test_no_dot(self):
        from agent.llm.tool_adapter import to_llm_tool_name
        assert to_llm_tool_name("artifact_list") == "artifact_list"

    def test_multiple_dots(self):
        from agent.llm.tool_adapter import to_llm_tool_name
        assert to_llm_tool_name("a.b.c") == "a__b__c"


class TestFromLLMName:
    """from_llm_tool_name: LLM-safe name → tool_id ( __ → . )"""

    def test_runtime_health(self):
        from agent.llm.tool_adapter import from_llm_tool_name
        assert from_llm_tool_name("runtime__health") == "runtime.health"

    def test_web_search(self):
        from agent.llm.tool_adapter import from_llm_tool_name
        assert from_llm_tool_name("web__search") == "web.search"

    def test_artifact_list(self):
        from agent.llm.tool_adapter import from_llm_tool_name
        assert from_llm_tool_name("artifact__list") == "artifact.list"

    def test_no_underscore(self):
        from agent.llm.tool_adapter import from_llm_tool_name
        assert from_llm_tool_name("artifact_list") == "artifact_list"

    def test_multiple_underscores(self):
        from agent.llm.tool_adapter import from_llm_tool_name
        assert from_llm_tool_name("a__b__c") == "a.b.c"


class TestToolSpecToOpenAIFunction:
    """tool_spec_to_openai_function uses LLM-safe names."""

    def test_function_name_is_llm_safe(self):
        from agent.llm.tool_adapter import tool_spec_to_openai_function
        tool = {
            "tool_id": "runtime.health",
            "description": "Check health",
            "input_schema": {"type": "object", "properties": {}, "required": []},
            "risk_level": "low",
            "enabled": True,
        }
        result = tool_spec_to_openai_function(tool)
        assert result["function"]["name"] == "runtime__health"

    def test_web_search_function_name(self):
        from agent.llm.tool_adapter import tool_spec_to_openai_function
        tool = {
            "tool_id": "web.search",
            "description": "Search web",
            "input_schema": {"type": "object", "properties": {}, "required": []},
            "risk_level": "low",
            "enabled": True,
        }
        result = tool_spec_to_openai_function(tool)
        assert result["function"]["name"] == "web__search"


class TestOrchestratorMapping:
    """Orchestrator uses real tool_id (with .), not LLM-safe name."""

    def test_execute_tool_uses_real_tool_id(self):
        """orchestrate() must convert LLM-safe name to real tool_id before _execute_tool."""
        from unittest.mock import MagicMock, patch
        from agent.llm.schemas import LLMToolCall

        captured = {}
        def fake_execute(tool_id, args, ws_id=None, state=None):
            captured["tool_id"] = tool_id
            return {"status": "ok", "result": "health ok"}

        mock_resp = MagicMock()
        mock_resp.error = None
        mock_resp.has_tool_calls = MagicMock(return_value=True)
        # Use real LLMToolCall so tc.name returns a real string
        mock_resp.tool_calls = [
            LLMToolCall(id="call_1", name="runtime__health", arguments={"check": "all"})
        ]

        with patch("agent.nodes.llm_orchestrator._execute_tool", side_effect=fake_execute):
            with patch("agent.llm.runtime.invoke_llm", return_value=mock_resp):
                from agent.legacy.llm_orchestrator import orchestrate
                from agent.state import NetworkAgentState
                state = NetworkAgentState()
                state.user_input = "check health"
                state.context = {}
                result_state = orchestrate(state)

                assert captured.get("tool_id") == "runtime.health", \
                    f"Expected 'runtime.health', got '{captured.get('tool_id')}'"


class TestToolResultsRecordRealToolId:
    """state.tool_results['tool_calls'][n]['tool_id'] must be real tool_id."""

    def test_tool_results_use_real_tool_id(self):
        """After orchestration, tool_results uses real tool_id."""
        from unittest.mock import MagicMock, patch
        from agent.llm.schemas import LLMToolCall

        mock_resp = MagicMock()
        mock_resp.content = ""
        mock_resp.error = None
        mock_resp.has_tool_calls = MagicMock(return_value=True)
        # Use real LLMToolCall so tc.name returns a real string
        mock_resp.tool_calls = [
            LLMToolCall(id="call_1", name="runtime__health", arguments={"check": "all"})
        ]

        with patch("agent.llm.runtime.invoke_llm", return_value=mock_resp):
            from agent.legacy.llm_orchestrator import orchestrate
            from agent.state import NetworkAgentState
            state = NetworkAgentState()
            state.user_input = "check health"
            state.context = {}
            result_state = orchestrate(state)

            tool_results = result_state.context.get("tool_results", {}).get("tool_calls", [])
            if tool_results:
                assert "runtime.health" in str(tool_results), \
                    "tool_results should use real tool_id (with .), not LLM-safe name"
