"""Tests for SPEG v3.13 Conversation Context Injection.

Verifies that session.history is correctly injected into SPEG so that
follow-up queries like "什么意思", "我上句话说了什么" can reference
previous turns instead of claiming ignorance.
"""

import asyncio
import pytest
from unittest import mock
from types import SimpleNamespace

from speg_engine.fast_path import (
    is_conversation_ref,
    _build_conversation_history_block,
    classify_direct_answer,
)
from speg_engine import SPEGConfig, SPEGEngine
from speg_engine.models import StatelessContext, ExecutionNode, ExecutionDAG, ToolResult
from agent.runtime.speg_adapter import _inject_conversation_context


# ============================================================================
# Unit: is_conversation_ref()
# ============================================================================

class TestConversationRefClassifier:
    """is_conversation_ref() standalone tests."""

    def test_wo_shang_ju_shuo_le_shenme(self):
        assert is_conversation_ref("我上句话说了什么") is True

    def test_shang_ju_shi_shenme(self):
        assert is_conversation_ref("上句是什么") is True

    def test_gangcai_wo_shuo_le_shenme(self):
        assert is_conversation_ref("刚才我说了什么") is True

    def test_nihai_jide_wogangcai(self):
        assert is_conversation_ref("你还记得我刚才说什么吗") is True

    def test_shenme_yisi(self):
        assert is_conversation_ref("什么意思") is True

    def test_zhe_shi_shenme_yisi(self):
        assert is_conversation_ref("这是什么意思") is True

    def test_ni_shuo_le_shenme_haijide_ma(self):
        assert is_conversation_ref("你说了什么还记得吗") is True

    def test_haijide_ma(self):
        assert is_conversation_ref("还记得吗") is True

    def test_wo_shuo_le_shenme(self):
        assert is_conversation_ref("我说了什么") is True

    def test_normal_question_not_ref(self):
        assert is_conversation_ref("解释一下 OSPF 是什么") is False

    def test_greeting_not_ref(self):
        assert is_conversation_ref("你好") is False

    def test_cmdb_inspection_not_ref(self):
        assert is_conversation_ref("我想对 CMDB 区域「广域网」发起自动巡检") is False

    def test_empty_input_not_ref(self):
        assert is_conversation_ref("") is False

    def test_pure_tool_request_not_ref(self):
        assert is_conversation_ref("ping 8.8.8.8") is False


# ============================================================================
# Unit: _inject_conversation_context()
# ============================================================================

class TestConversationContextInjection:
    """_inject_conversation_context() unit tests based on session.history."""

    def _make_msg(self, role: str, content: str):
        return SimpleNamespace(role=role, content=content)

    def _make_session(self, history: list):
        return SimpleNamespace(history=history)

    def test_empty_history(self):
        session = self._make_session([])
        metadata = {}
        _inject_conversation_context(session, metadata)
        assert "conversation_history" in metadata
        assert len(metadata["conversation_history"]) == 0

    def test_null_history(self):
        session = SimpleNamespace(history=None)
        metadata = {}
        _inject_conversation_context(session, metadata)
        # Still injects empty conversation_context
        assert "conversation_context" in metadata

    def test_single_user_message(self):
        session = self._make_session([
            self._make_msg("user", "我想对 CMDB 区域「广域网」发起自动巡检"),
        ])
        metadata = {}
        _inject_conversation_context(session, metadata)

        assert "conversation_history" in metadata
        hist = metadata["conversation_history"]
        assert any("CMDB" in m.get("content", "") for m in hist)

        conv_ctx = metadata.get("conversation_context")
        assert conv_ctx is not None
        assert conv_ctx.previous_user_message == "我想对 CMDB 区域「广域网」发起自动巡检"

    def test_two_turns_user_assistant(self):
        session = self._make_session([
            self._make_msg("user", "我想对 CMDB 区域「广域网」发起自动巡检"),
            self._make_msg("assistant", "收到。正在规划中……\n\nNo tools were executed."),
        ])
        metadata = {}
        _inject_conversation_context(session, metadata)

        hist = metadata["conversation_history"]
        assert len(hist) >= 2
        roles = [m["role"] for m in hist]
        assert "user" in roles
        assert "assistant" in roles
        assert "No tools were executed" in str(hist)

        conv_ctx = metadata["conversation_context"]
        assert conv_ctx.previous_assistant_message == "收到。正在规划中……\n\nNo tools were executed."

    def test_multi_turn_history(self):
        # Long messages force older turns into session_summary
        msgs = []
        for i in range(15):
            msgs.append(self._make_msg("user", f"这是一个很长的问题 {i} " + "数据" * 80))
            msgs.append(self._make_msg("assistant", f"这是一个很长的回答 {i} " + "结果" * 80))
        session = self._make_session(msgs)
        metadata = {}
        _inject_conversation_context(session, metadata)

        conv_ctx = metadata["conversation_context"]
        assert conv_ctx is not None
        # With 320+ chars per message × 30 messages = 9600+ > 8000 budget
        # Some should go to recent window, older ones to session_summary
        assert len(conv_ctx.recent_messages) >= 2
        assert conv_ctx.previous_user_message == "这是一个很长的问题 14 " + "数据" * 80

    def test_long_content_truncation(self):
        long_content = "A" * 2000
        session = self._make_session([
            self._make_msg("user", long_content),
            self._make_msg("assistant", "ok"),
        ])
        metadata = {}
        _inject_conversation_context(session, metadata)

        hist = metadata["conversation_history"]
        assert len(hist) >= 1
        # v3.14: max per message is 3000 chars, so 2000 fits
        # but it should be within the window budget
        assert all(len(m.get("content", "")) <= 3000 for m in hist)

    def test_total_char_cap(self):
        # Many messages → older ones go to session_summary
        msgs = []
        for i in range(20):
            msgs.append(self._make_msg("user", f"message-{i:03d}-" + "X" * 680))
            msgs.append(self._make_msg("assistant", f"reply-{i:03d}-" + "Y" * 680))
        session = self._make_session(msgs)
        metadata = {}
        _inject_conversation_context(session, metadata)

        hist = metadata["conversation_history"]
        # Recent window should not include all 40 messages
        assert len(hist) < 30
        assert len(hist) >= 1

        # Older turns should be summarized
        conv_ctx = metadata["conversation_context"]
        assert conv_ctx is not None

    def test_no_session_attribute(self):
        session = SimpleNamespace()
        metadata = {}
        _inject_conversation_context(session, metadata)
        assert "conversation_context" in metadata
        assert metadata["conversation_history"] == []

    def test_none_session(self):
        metadata = {}
        try:
            _inject_conversation_context(None, metadata)
        except Exception:
            pytest.fail("_inject_conversation_context should not raise on None session")


# ============================================================================
# Unit: _build_conversation_history_block()
# ============================================================================

class TestHistoryBlockFormatting:
    """_build_conversation_history_block() formatting tests."""

    def test_empty_history(self):
        assert _build_conversation_history_block([]) == ""

    def test_single_entry(self):
        hist = [{"role": "user", "content": "你好"}]
        block = _build_conversation_history_block(hist)
        assert "RECENT CONVERSATION HISTORY" in block
        assert "[1] user: 你好" in block

    def test_multiple_entries(self):
        hist = [
            {"role": "user", "content": "CMDB 巡检"},
            {"role": "assistant", "content": "No tools were executed."},
        ]
        block = _build_conversation_history_block(hist)
        assert "[1] user: CMDB 巡检" in block
        assert "[2] assistant: No tools were executed." in block


# ============================================================================
# Integration: SPEGEngine fast-path + conversation_ref
# ============================================================================

class TestFastPathWithConversationRef:
    """Verify that conversation_ref queries receive history in direct-answer."""

    def _build_engine_with_history(self, history_entries, llm_response="基于对话历史，您上一句提到..."):
        """Build SPEGEngine with conversation_history injected via ctx.extras."""

        # We bypass speg_adapter and inject history directly into
        # engine.run(extras=) — this simulates what speg_adapter does.
        extras = {}
        mock_session = SimpleNamespace(history=[
            SimpleNamespace(role=e["role"], content=e["content"])
            for e in history_entries
        ])
        _inject_conversation_context(mock_session, extras)

        llm_calls = []

        def llm_mock(**kwargs):
            llm_calls.append({
                "system": kwargs.get("system", ""),
                "user": kwargs.get("user", ""),
                "extra": kwargs.get("extra", {}),
            })
            return llm_response

        config = SPEGConfig()
        engine = SPEGEngine(
            config=config, llm_invoke=llm_mock,
            tool_runtime=mock.MagicMock(),
        )
        return engine, extras, llm_calls

    def test_conversation_ref_injects_history_into_prompt(self):
        """'我上句话说了什么' with CMDB history → LLM sees history."""
        engine, extras, llm_calls = self._build_engine_with_history(
            [{"role": "user", "content": "我想对 CMDB 区域「广域网」发起自动巡检"}],
        )

        result = asyncio.run(engine.run(
            user_input="我上句话说了什么",
            workspace_id="test",
            extras=extras,
        ))
        assert result.success
        meta = result.metadata
        assert meta.get("fast_path") is True, "conversation ref should hit fast path"
        assert meta.get("conversation_ref") is True
        assert meta.get("conversation_history_used") is True

        # LLM should have received history in its system prompt
        system_prompt = llm_calls[0]["system"]
        assert "RECENT CONVERSATION HISTORY" in system_prompt
        assert "CMDB" in system_prompt
        assert "广域网" in system_prompt
        assert "自动巡检" in system_prompt

    def test_shenme_yisi_with_history(self):
        """'什么意思' after 'No tools were executed.' → LLM sees both."""
        engine, extras, llm_calls = self._build_engine_with_history(
            [
                {"role": "user", "content": "我想对 CMDB 区域「广域网」发起自动巡检"},
                {"role": "assistant", "content": "收到。正在规划中……\n\nNo tools were executed."},
            ],
            llm_response=(
                "意思是当前没有执行任何工具/巡检任务。"
                "您的上一轮请求是对 CMDB 区域「广域网」进行自动巡检，"
                "但系统未能实际执行工具。"
            ),
        )

        result = asyncio.run(engine.run(
            user_input="什么意思",
            workspace_id="test",
            extras=extras,
        ))
        assert result.success
        meta = result.metadata
        assert meta.get("conversation_ref") is True

        system_prompt = llm_calls[0]["system"]
        assert "No tools were executed" in system_prompt
        assert "CMDB" in system_prompt

        # Response should reference CMDB inspection request
        assert "CMDB" in result.final_response

    def test_no_history_no_conversation_ref_flag(self):
        """Without history, '什么意思' goes through planner (not fast path
        since it doesn't match '是什么').  The LLM mock returns empty nodes."""
        extras = {}
        llm_calls = []

        def llm_mock(**kwargs):
            llm_calls.append(kwargs)
            return '{"nodes": []}'  # valid planner JSON, no tools

        config = SPEGConfig()
        engine = SPEGEngine(
            config=config, llm_invoke=llm_mock,
            tool_runtime=mock.MagicMock(),
        )

        result = asyncio.run(engine.run(
            user_input="什么意思",
            workspace_id="test",
            extras=extras,
        ))
        assert result.success
        meta = result.metadata
        # "什么意思" does NOT match fast-path whitelist, and there's no
        # history to trigger conversation-ref override → full SPEG.
        assert meta.get("fast_path") is False
        assert meta.get("conversation_ref") is False
        assert meta.get("conversation_history_used") is False

    def test_normal_question_unaffected(self):
        """A normal question with history → no injection, no ref flag."""
        engine, extras, llm_calls = self._build_engine_with_history(
            [{"role": "user", "content": "你好"}, {"role": "assistant", "content": "你好！"}],
        )

        result = asyncio.run(engine.run(
            user_input="解释一下 OSPF 是什么",
            workspace_id="test",
            extras=extras,
        ))
        assert result.success
        meta = result.metadata
        assert meta.get("fast_path") is True
        assert meta.get("route") == "simple_question"
        # Not a conversation_ref
        assert meta.get("conversation_ref") is False

    def test_complex_query_with_ref_pattern_but_no_history(self):
        """'我说了什么' without history — no ref flag, planner runs."""
        extras = {}
        llm_calls = []

        def llm_mock(**kwargs):
            llm_calls.append(kwargs)
            return '{"nodes": []}'  # valid planner JSON

        config = SPEGConfig()
        engine = SPEGEngine(
            config=config, llm_invoke=llm_mock,
            tool_runtime=mock.MagicMock(),
        )

        result = asyncio.run(engine.run(
            user_input="我说了什么",
            workspace_id="test",
            extras=extras,
        ))
        assert result.success
        meta = result.metadata
        # Without history, "我说了什么" doesn't match fast-path whitelist
        # and no conversation_ref override → full SPEG.
        assert meta.get("conversation_ref") is False


# ============================================================================
# Integration: Planner receives history
# ============================================================================

class TestPlannerReceivesHistory:
    """Verify that the planner prompt includes conversation_history."""

    def test_planner_sees_history_in_prompt(self):
        """Non-fast-path, non-task-intent query → planner block."""
        extras = {
            "conversation_history": [
                {"role": "user", "content": "CMDB 巡检请求"},
            ],
        }
        planner_inputs = []

        def llm_mock(**kwargs):
            planner_inputs.append(kwargs)
            return '{"nodes": []}'

        engine = SPEGEngine(config=SPEGConfig(), llm_invoke=llm_mock, tool_runtime=mock.MagicMock())

        result = asyncio.run(engine.run(
            user_input="请描述 OSPF 邻居状态列表",
            workspace_id="test", extras=extras,
        ))
        assert result.success
        assert planner_inputs
        prompt = planner_inputs[0].get("user", "")
        assert "RECENT CONVERSATION HISTORY" in prompt or "CMDB" in prompt

    def test_planner_without_history(self):
        """No history → planner prompt has no history block."""
        planner_inputs = []

        def llm_mock(**kwargs):
            planner_inputs.append(kwargs)
            return '{"nodes": []}'

        config = SPEGConfig()
        engine = SPEGEngine(
            config=config, llm_invoke=llm_mock,
            tool_runtime=mock.MagicMock(),
        )

        result = asyncio.run(engine.run(
            user_input="OSPF 有哪些邻居状态",
            workspace_id="test",
        ))
        assert result.success

        planner_user_prompt = planner_inputs[0].get("user", "")
        assert "RECENT CONVERSATION HISTORY" not in planner_user_prompt


# ============================================================================
# Integration: Finalizer receives history
# ============================================================================

class TestFinalizerReceivesHistory:
    """Verify finalizer prompt includes conversation_history."""

    def test_finalizer_sees_history_in_no_tools_path(self):
        """Non-task, non-fast-path query with history → finalizer prompt."""
        extras = {
            "conversation_history": [{"role": "user", "content": "帮我巡检"}],
        }
        llm_outputs = []

        def llm_mock(**kwargs):
            llm_outputs.append(kwargs.get("user", ""))
            return '{"nodes": []}'

        engine = SPEGEngine(config=SPEGConfig(enable_finalizer=True), llm_invoke=llm_mock,
                            tool_runtime=mock.MagicMock())

        result = asyncio.run(engine.run(
            user_input="OSPF 协议的邻居状态有哪些种",
            workspace_id="test", extras=extras,
        ))
        assert result.success
        finalizer_prompt = llm_outputs[-1] if len(llm_outputs) >= 2 else ""
        assert "ORIGINAL USER REQUEST" in finalizer_prompt or "OSPF" in finalizer_prompt

    def test_finalizer_without_history(self):
        llm_outputs = []

        def llm_mock(**kwargs):
            llm_outputs.append(kwargs.get("user", ""))
            return '{"nodes": []}'

        engine = SPEGEngine(config=SPEGConfig(enable_finalizer=True), llm_invoke=llm_mock,
                            tool_runtime=mock.MagicMock())

        result = asyncio.run(engine.run(
            user_input="OSPF 协议的邻居状态有哪些种",
            workspace_id="test",
        ))
        assert result.success
        assert llm_outputs


# ============================================================================
# Integration: Planner system prompt includes rule 13
# ============================================================================

class TestPlannerSystemPrompt:
    """Verify the planner system prompt includes conversation-ref rules."""

    def test_planner_system_prompt_rule_13(self):
        from speg_engine.planner import PLANNER_SYSTEM_PROMPT

        assert "RECENT CONVERSATION HISTORY" in PLANNER_SYSTEM_PROMPT
        assert "我上句话说了什么" in PLANNER_SYSTEM_PROMPT
        assert "final_response" in PLANNER_SYSTEM_PROMPT
        assert "memory.manage" in PLANNER_SYSTEM_PROMPT
