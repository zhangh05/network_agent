"""SPEG Main Pipeline E2E — 10 end-to-end tests covering the full
Context→Intent→Plan→Execute→Merge→Synthesize→Validate→Persist chain.

v3.14: Section 9 acceptance tests.
"""

import asyncio
import pytest
from unittest import mock
from types import SimpleNamespace

from speg_engine import SPEGConfig, SPEGEngine
from speg_engine.models import ToolResult, ConversationContext
from speg_engine.engine import (
    detect_task_intent,
    validate_final_response,
    TaskIntentResult,
    FinalResponseValidatorResult,
)
from agent.runtime.speg_adapter import (
    _inject_conversation_context,
    _sync_session_history,
)
from agent.protocol.message import UserMessage, AssistantMessage


# ============================================================================
# Helpers
# ============================================================================

def _make_session(history=None):
    s = SimpleNamespace(
        session_id="test-session-1",
        workspace_id="test",
        history=history or [],
    )
    return s

def _make_msg(role, content):
    return SimpleNamespace(role=role, content=content)


# ============================================================================
# E2E 1: Conversation continuity — next turn sees previous
# ============================================================================

class TestConversationContinuity:
    """同一活跃 session 内多轮上下文不丢失。"""

    def test_next_turn_sees_previous_with_sync(self):
        """_sync_session_history → next _inject_conversation_context works."""
        session = _make_session()
        user_input = "我想对 ASBR-PE1 发起巡检"
        final_response = "巡检任务已创建。"
        _sync_session_history(session, user_input, final_response)

        assert len(session.history) == 2
        assert session.history[0].content == user_input
        assert session.history[1].content == final_response

        meta = {}
        _inject_conversation_context(session, meta)
        assert "ASBR-PE1" in meta.get("previous_user_message", "")

    def test_two_turns_no_sync(self):
        """Without _sync_session_history, context is empty."""
        session = _make_session()
        meta = {}
        _inject_conversation_context(session, meta)
        assert meta.get("previous_user_message", "") == ""

    def test_two_turns_with_sync(self):
        """Two turns, both with sync → second turn sees first."""
        session = _make_session()

        _sync_session_history(session, "巡检 ASBR-PE1", "ok")
        _sync_session_history(session, "分析 TCP 报文", "分析完成")

        meta = {}
        _inject_conversation_context(session, meta)
        assert meta.get("previous_user_message", "") == "分析 TCP 报文"


# ============================================================================
# E2E 2: task_intent_detector
# ============================================================================

class TestTaskIntentDetectionPipeline:
    """unified task_intent_detector."""

    def test_inspection_task(self):
        r = detect_task_intent("我想对 CMDB 发起自动巡检")
        assert r.is_task
        assert r.intent_type == "inspection"

    def test_file_analysis(self):
        r = detect_task_intent("读取这个报文并分析")
        assert r.is_task

    def test_definition_excluded(self):
        for q in ("OSPF 是什么", "什么是 BGP", "NAT 是什么"):
            assert detect_task_intent(q).is_task is False

    def test_what_problem_still_task(self):
        assert detect_task_intent("帮我分析这是什么问题").is_task is True

    def test_why_screenshot_still_task(self):
        assert detect_task_intent("这个截图为什么会这样").is_task is True

    def test_look_at_log_still_task(self):
        assert detect_task_intent("读取这个日志看看是什么异常").is_task is True


# ============================================================================
# E2E 3: Empty-plan guard
# ============================================================================

class TestEmptyPlanGuardPipeline:
    """Planner nodes=[] + task intent → error."""

    def test_analyse_with_empty_nodes_fails(self):
        llm = mock.Mock(return_value='{"nodes": []}')
        engine = SPEGEngine(config=SPEGConfig(), llm_invoke=llm, tool_runtime=mock.MagicMock())
        result = asyncio.run(engine.run(user_input="帮我分析这个报文是什么问题", workspace_id="test"))
        assert result.success is False
        structured = result.metadata.get("structured_errors", [])
        codes = [e.get("code", "") for e in structured]
        assert "PLANNER_EMPTY_FOR_TASK_INTENT" in codes

    def test_inspection_with_empty_nodes_fails(self):
        llm = mock.Mock(return_value='{"nodes": []}')
        engine = SPEGEngine(config=SPEGConfig(), llm_invoke=llm, tool_runtime=mock.MagicMock())
        result = asyncio.run(engine.run(user_input="巡检 CMDB", workspace_id="test"))
        assert result.success is False


# ============================================================================
# E2E 4: Validator — no false positives
# ============================================================================

class TestValidatorNoFalsePositive:
    """validate_final_response doesn't kill good answers."""

    def test_inspection_completed_with_conclusions(self):
        resp = "巡检已完成，结论如下：ASBR-PE1 正常，无严重告警。建议定期复查。"
        v = validate_final_response("巡检 CMDB", resp)
        assert v.valid is True

    def test_file_read_with_analysis(self):
        resp = "文件读取已完成，分析结论如下：TCP 连接正常，无异常报文。"
        v = validate_final_response("读取文件并分析", resp)
        assert v.valid is True

    def test_command_result_with_exception(self):
        resp = "命令执行完成，发现以下异常：接口 eth0 存在丢包。原因：MTU 不匹配。"
        v = validate_final_response("执行命令检查", resp)
        assert v.valid is True

    def test_placeholder_caught(self):
        v = validate_final_response("分析数据", "已完成。")
        assert v.valid is False

    def test_completed_placeholder_caught(self):
        v = validate_final_response("分析数据", "收到")
        assert v.valid is False


# ============================================================================
# E2E 5: File read analysis closure
# ============================================================================

class TestFileReadAnalysisClosure:
    """File read → normalized_content → analysis conclusion."""

    def test_read_file_gets_analysis(self):
        llm_outputs = []

        def llm_mock(**kwargs):
            llm_outputs.append(kwargs.get("user", ""))
            if "planner" in (kwargs.get("system", "") or "").lower():
                return '{"nodes": [{"id": "n1", "tool": "workspace.file", "args": {"action": "read", "file": "tcp.txt"}, "deps": []}]}'
            return "TCP报文分析：源地址 192.168.5.12 到目标 192.168.5.8:3389，三次握手完成，未见异常。建议：持续监控。"

        tr = mock.MagicMock()
        async def m_exec(nodes, ctx, all_r):
            return {"n1": ToolResult(node_id="n1", tool="workspace.file", success=True,
                                     data={"output": {"content": "192.168.5.12:63028 -> 192.168.5.8:3389 SYN SYN-ACK ACK"}})}
        tr.execute_layer = m_exec

        engine = SPEGEngine(config=SPEGConfig(enable_finalizer=True, max_llm_calls=3),
                            llm_invoke=llm_mock, tool_runtime=tr)
        engine.register_tool("workspace.file", mock.AsyncMock(), description="File ops")

        r = asyncio.run(engine.run(user_input="读取这个 txt 报文文件并分析有什么问题", workspace_id="test"))
        assert r.success
        assert "192.168" in r.final_response or "TCP" in r.final_response


# ============================================================================
# E2E 6: Long history → session_summary retrieval
# ============================================================================

class TestLongHistoryRetrieval:
    """第20轮之后仍能通过 context 找回早期引用。"""

    def test_long_history_session_summary(self):
        session = _make_session()
        # First mention ASBR-PE1
        for i in range(20):
            _sync_session_history(session, f"普通对话 {i}", f"回复 {i}")

        meta = {}
        _inject_conversation_context(session, meta)
        cc = meta.get("conversation_context")
        assert cc is not None
        # Recent messages should exist
        assert len(cc.recent_messages) >= 2
        # Session summary should have older turns
        # (20 turns × ~50 chars each = 1000+ chars with summaries)
        assert cc.has_context

    def test_long_history_with_asbr(self):
        session = _make_session()
        _sync_session_history(session, "检查 ASBR-PE1 设备状态", "设备正常")
        for i in range(15):
            _sync_session_history(session, f"随便聊 {i}", f"好 {i}")
        _sync_session_history(session, "继续处理刚才提到的设备", "...")

        meta = {}
        _inject_conversation_context(session, meta)
        cc = meta.get("conversation_context")
        assert cc is not None
        # The most recent user message should be "继续处理刚才提到的设备"
        assert "刚才" in cc.previous_user_message


# ============================================================================
# E2E 7: ConversationContext format_for_prompt
# ============================================================================

class TestConversationContextFormat:
    def test_full_format(self):
        cc = ConversationContext(
            session_summary="之前讨论了网络设备巡检。",
            recent_messages=[
                {"role": "user", "content": "巡检 ASBR-PE1"},
                {"role": "assistant", "content": "无异常"},
            ],
            retrieved_history=[
                {"role": "user", "content": "前面提到的 ASBR-PE1"},
            ],
        )
        block = cc.format_for_prompt()
        assert "SESSION SUMMARY" in block
        assert "RECENT CONVERSATION HISTORY" in block
        assert "ASBR-PE1" in block
        assert "RETRIEVED HISTORY" in block

    def test_partial_format(self):
        cc = ConversationContext(
            recent_messages=[{"role": "user", "content": "hi"}],
        )
        block = cc.format_for_prompt()
        assert "RECENT CONVERSATION HISTORY" in block
        assert "SESSION SUMMARY" not in block