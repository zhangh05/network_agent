"""SSOT Runtime Main Pipeline E2E — 10 end-to-end tests covering the full
Context→Intent→Plan→Execute→Merge→Synthesize→Validate→Persist chain.

v3.14: Section 9 acceptance tests.
"""

import asyncio
import pytest
from unittest import mock
from types import SimpleNamespace

from core.runtime_engine import SSOTRuntimeConfig, SSOTRuntimeEngine
from core.runtime_engine.models import ToolResult
from core.runtime_engine.engine import (
    detect_task_intent,
    validate_final_response,
    TaskIntentResult,
    FinalResponseValidatorResult,
)
from agent.runtime.ssot_runtime import (
    _build_history_block,
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
    """Same active session — multi-turn context preserved."""

    def test_next_turn_sees_previous_with_sync(self):
        """_sync_session_history → _build_history_block works."""
        session = _make_session()
        user_input = "我想对 ASBR-PE1 发起巡检"
        final_response = "巡检任务已创建。"
        _sync_session_history(session, user_input, final_response)

        assert len(session.history) == 2
        assert session.history[0].content == user_input
        assert session.history[1].content == final_response

        block = _build_history_block(session)
        assert "ASBR-PE1" in block

    def test_two_turns_no_sync(self):
        """Without _sync_session_history, context is empty."""
        session = _make_session()
        block = _build_history_block(session)
        assert block == ""

    def test_two_turns_with_sync(self):
        """Two turns, both with sync → second turn sees first."""
        session = _make_session()

        _sync_session_history(session, "巡检 ASBR-PE1", "ok")
        _sync_session_history(session, "分析 TCP 报文", "分析完成")

        block = _build_history_block(session)
        assert "分析 TCP 报文" in block


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
        engine = SSOTRuntimeEngine(config=SSOTRuntimeConfig(), llm_invoke=llm, tool_runtime=mock.MagicMock())
        result = asyncio.run(engine.run(user_input="帮我分析这个报文是什么问题", workspace_id="test"))
        assert result.success is False
        structured = result.metadata.get("structured_errors", [])
        codes = [e.get("code", "") for e in structured]
        assert "PLANNER_EMPTY_FOR_TASK_INTENT" in codes

    def test_inspection_with_empty_nodes_fails(self):
        llm = mock.Mock(return_value='{"nodes": []}')
        engine = SSOTRuntimeEngine(config=SSOTRuntimeConfig(), llm_invoke=llm, tool_runtime=mock.MagicMock())
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

        engine = SSOTRuntimeEngine(config=SSOTRuntimeConfig(enable_finalizer=True, max_llm_calls=3),
                            llm_invoke=llm_mock, tool_runtime=tr)
        engine.register_tool("workspace.file", mock.AsyncMock(), description="File ops")

        r = asyncio.run(engine.run(user_input="读取这个 txt 报文文件并分析有什么问题", workspace_id="test"))
        assert r.success
        assert "192.168" in r.final_response or "TCP" in r.final_response


# ============================================================================
# E2E 6: Long history → session_summary retrieval
# ============================================================================

class TestLongHistoryRetrieval:
    """Long sessions keep important early entities through summary/retrieval."""

    def test_long_history_real_entity_retrieval(self):
        """第1轮提到 ASBR-PE1，第22轮问'前面的设备'，必须找回 ASBR-PE1."""
        session = _make_session()

        # Turn 1: establish key entity
        _sync_session_history(session,
            "后面记住这个设备：ASBR-PE1，它属于广域网区域",
            "已记录当前会话上下文：ASBR-PE1（广域网区域）。")

        # Turns 2-21: random noise
        for i in range(2, 22):
            _sync_session_history(session,
                f"这是第 {i} 轮普通对话",
                f"这是第 {i} 轮普通回复")

        block = _build_history_block(session, user_input="前面提到的那个设备继续巡检")
        assert "ASBR-PE1" in block
        assert "广域网" in block

    def test_long_history_preserved(self):
        """History block keeps most recent turns within budget."""
        session = _make_session()
        _sync_session_history(session, "记住 ASBR-PE1，广域网区域", "已记录。")
        for i in range(2):  # Only 2 extra turns — ASBR-PE1 stays visible
            _sync_session_history(session, f"对话 {i}", f"回复 {i}")

        block = _build_history_block(session)
        assert "ASBR-PE1" in block

    def test_empty_session_returns_empty(self):
        """Empty session returns empty history block."""
        session = SimpleNamespace(
            session_id="test-empty",
            workspace_id="test",
            history=[],
        )
        block = _build_history_block(session)
        assert block == ""


# ============================================================================
# E2E 7: Validator — bogus responses caught
# ============================================================================

class TestValidatorBogusResponses:
    """validate_final_response catches non-analysis responses."""

    def test_tool_success_without_analysis_is_invalid(self):
        v = validate_final_response("读取文件并分析",
            "工具执行成功，文件内容已读取，后续可以继续处理。")
        assert v.valid is False

    def test_file_read_without_conclusion_is_invalid(self):
        v = validate_final_response("读取文件并分析",
            "文件已读取，可以继续分析。")
        assert v.valid is False

    def test_explicit_failure_is_valid(self):
        v = validate_final_response("分析报文",
            "无法完成分析：工具未返回正文内容，缺少可分析报文数据。")
        assert v.valid is True
        assert v.has_explicit_failure_reason is True

    def test_real_analysis_is_valid(self):
        v = validate_final_response("分析报文",
            "文件读取完成，结论如下：TCP握手正常，未见RST，建议继续观察。")
        assert v.valid is True
        assert v.has_analysis_fields is True

