"""Agent Basic Conversation Tests — v0.1

Tests for assistant_chat intent and basic conversation capability.
"""
import pytest
from agent.state import NetworkAgentState
from agent.legacy.intent_router import route, _infer
from agent.legacy.composer import compose, _assistant_response


class TestIntentRouter:
    def test_hello_intent(self):
        """你好 should route to assistant_chat."""
        intent = _infer("你好")
        assert intent == "assistant_chat"

    def test_hi_intent(self):
        """hi should route to assistant_chat."""
        intent = _infer("hi")
        assert intent == "assistant_chat"

    def test_who_are_you_intent(self):
        intent = _infer("你是谁")
        assert intent == "assistant_chat"

    def test_what_can_you_do(self):
        intent = _infer("你能做什么")
        assert intent == "assistant_chat"

    def test_what_model_intent(self):
        intent = _infer("你是什么模型")
        assert intent == "assistant_chat"

    def test_memory_question_intent(self):
        intent = _infer("memory怎么回事")
        assert intent == "assistant_chat"

    def test_status_question_intent(self):
        intent = _infer("当前状态怎么样")
        assert intent == "assistant_chat"

    def test_llm_config_question_intent(self):
        intent = _infer("LLM配置在哪里")
        assert intent == "assistant_chat"

    def test_translate_still_works(self):
        intent = _infer("翻译配置")
        assert intent == "translate_config"

    def test_topology_planned(self):
        intent = _infer("帮我画拓扑")
        assert intent == "topology_draw"

    def test_route_topology_as_planned_capability(self):
        state = NetworkAgentState(user_input="帮我画拓扑")
        state = route(state)
        assert state.intent == "topology_draw"
        assert state.context.get("capability_status") == "planned"
        assert state.context.get("capability_id") == "topology"
        assert state.selected_skill == "topology"

    def test_help_intent(self):
        intent = _infer("help")
        assert intent == "assistant_chat"

    def test_route_with_assistant_chat_state(self):
        state = NetworkAgentState(user_input="你好")
        state = route(state)
        assert state.intent == "assistant_chat"


class TestAssistantResponse:
    def test_hello_response(self):
        state = NetworkAgentState(user_input="你好", intent="assistant_chat")
        resp = _assistant_response(state)
        assert "你好" in resp or "hello" in resp.lower()

    def test_capability_response(self):
        state = NetworkAgentState(user_input="你能做什么", intent="assistant_chat")
        resp = _assistant_response(state)
        assert "配置翻译" in resp or "config_translation" in resp

    def test_identity_response(self):
        state = NetworkAgentState(user_input="你是谁", intent="assistant_chat")
        resp = _assistant_response(state)
        assert "Network Agent" in resp

    def test_model_response(self):
        state = NetworkAgentState(user_input="你是什么模型", intent="assistant_chat")
        resp = _assistant_response(state)
        assert "Network Agent" in resp
        assert "LLM" in resp or "assistant_chat" in resp
        assert "provider=" in resp or "deterministic assistant_chat" in resp
        assert "人工复核" not in resp

    def test_memory_response(self):
        state = NetworkAgentState(user_input="memory怎么回事", intent="assistant_chat")
        resp = _assistant_response(state)
        assert "Memory" in resp
        assert "localStorage" in resp
        assert "source_config" in resp

    def test_status_response(self):
        state = NetworkAgentState(user_input="当前状态怎么样", intent="assistant_chat")
        resp = _assistant_response(state)
        assert "0.0.0.0:8010" in resp
        assert "config_translation" in resp

    def test_no_deployable_config(self):
        state = NetworkAgentState(user_input="你好", intent="assistant_chat")
        resp = _assistant_response(state)
        assert "deployable" not in resp.lower() or "not" in resp.lower()

    def test_planned_mentioned(self):
        state = NetworkAgentState(user_input="你能做什么", intent="assistant_chat")
        resp = _assistant_response(state)
        assert "plan" in resp.lower() or "coming" in resp.lower() or "规划" in resp

    def test_compose_handles_assistant_chat(self):
        state = NetworkAgentState(user_input="你好", intent="assistant_chat")
        state = compose(state)
        assert state.final_response is not None
        assert "didn't understand" not in state.final_response


class TestNoopExecutor:
    def test_assistant_chat_noop(self):
        from agent.legacy.skill_executor import execute
        state = NetworkAgentState(user_input="你好", intent="assistant_chat",
                                  selected_skill=None)
        state = execute(state)
        # Should not set error for assistant_chat
        assert state.error is None or "No skill" not in str(state.error)

    def test_translate_config_still_works_in_router(self):
        """translate_config should still route correctly."""
        state = NetworkAgentState(user_input="翻译 配置 cisco huawei")
        state = route(state)
        assert state.intent == "translate_config"
