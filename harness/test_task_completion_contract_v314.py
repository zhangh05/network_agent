"""Tests for SPEG v3.14 Task Completion Contract.

Verifies that SPEG no longer returns placeholder responses ("收到", "No tools
were executed") for task-intent requests.  Ensures:
  - Empty-plan task-intent → PLANNER_EMPTY_FOR_TASK_INTENT error
  - Tool execution success + task request → analysis conclusion (not just "收到")
  - normalized_content extraction and injection into finalizer prompt
  - Incomplete final_response → TASK_INCOMPLETE error
"""

import asyncio
import pytest
from unittest import mock
from types import SimpleNamespace

from speg_engine import SPEGConfig, SPEGEngine
from speg_engine.models import StatelessContext, ExecutionNode, ExecutionDAG, ToolResult
from speg_engine.engine import (
    plan_nodes_empty_for_task,
    _is_task_incomplete_final_response,
)
from speg_engine.result_merger import (
    ResultMerger,
    _extract_normalized_content,
    _get_nested,
)
from speg_engine.errors import SpegErrorCode


# ============================================================================
# Unit: task-intent detection
# ============================================================================

class TestTaskIntentDetection:
    """plan_nodes_empty_for_task() standalone tests."""

    def test_analyse_has_task_intent(self):
        assert plan_nodes_empty_for_task("分析这个 TCP 报文数据") is True

    def test_inspect_has_task_intent(self):
        assert plan_nodes_empty_for_task("我想对 CMDB 资产发起自动巡检") is True
        assert plan_nodes_empty_for_task("巡检区域广域网") is True

    def test_read_file_has_task_intent(self):
        assert plan_nodes_empty_for_task("读取配置文件并分析结果") is True

    def test_check_has_task_intent(self):
        assert plan_nodes_empty_for_task("检查设备状态") is True

    def test_generate_report_has_task_intent(self):
        assert plan_nodes_empty_for_task("生成一份检查报告") is True

    def test_summarise_has_task_intent(self):
        assert plan_nodes_empty_for_task("总结一下这些数据") is True

    def test_diagnose_has_task_intent(self):
        assert plan_nodes_empty_for_task("诊断网络故障原因") is True

    def test_compare_has_task_intent(self):
        assert plan_nodes_empty_for_task("对比两个配置") is True

    def test_definition_question_not_task_intent(self):
        assert plan_nodes_empty_for_task("OSPF 是什么") is False
        assert plan_nodes_empty_for_task("解释一下什么是 BGP") is False

    def test_introduce_not_task_intent(self):
        assert plan_nodes_empty_for_task("介绍一下这个功能") is False

    def test_greeting_not_task_intent(self):
        assert plan_nodes_empty_for_task("你好") is False

    def test_simple_question_not_task_intent(self):
        assert plan_nodes_empty_for_task("今天天气怎么样") is False

    def test_empty_not_task_intent(self):
        assert plan_nodes_empty_for_task("") is False


# ============================================================================
# Unit: incomplete response detection
# ============================================================================

class TestIncompleteResponseDetection:
    """_is_task_incomplete_final_response() tests."""

    def test_shou_dao_incomplete(self):
        assert _is_task_incomplete_final_response("分析数据", "收到") is True

    def test_completed_incomplete(self):
        assert _is_task_incomplete_final_response("分析数据", "已完成") is True

    def test_tool_chenggong_incomplete(self):
        assert _is_task_incomplete_final_response("分析数据", "工具调用成功") is True

    def test_no_tools_incomplete(self):
        assert _is_task_incomplete_final_response("分析数据", "No tools were executed") is True

    def test_readartifact_completed_incomplete(self):
        assert _is_task_incomplete_final_response("分析这个报文", "readartifact completed") is True

    def test_empty_response_incomplete(self):
        assert _is_task_incomplete_final_response("分析数据", "") is True

    def test_real_analysis_not_incomplete(self):
        resp = "报文分析显示 TCP 连接正常，三次握手完成，无丢包。"
        assert _is_task_incomplete_final_response("分析这个报文", resp) is False

    def test_non_task_input_not_checked(self):
        assert _is_task_incomplete_final_response("你好", "收到") is False
        assert _is_task_incomplete_final_response("OSPF 是什么", "") is False

    def test_no_tools_executed_with_prefix_incomplete(self):
        # "[TASK_INCOMPLETE] No tools were executed..." contains "No tools were executed"
        assert _is_task_incomplete_final_response(
            "巡检 CMDB", "[TASK_INCOMPLETE] No tools were executed for this request."
        ) is True


# ============================================================================
# Unit: normalized_content extraction
# ============================================================================

class TestNormalizedContentExtraction:
    """_extract_normalized_content() tests."""

    def test_readartifact_output_content(self):
        r = ToolResult(node_id="n1", tool="workspace.readartifact", success=True,
                       data={"output": {"content": "TCP报文数据..."}})
        nc = _extract_normalized_content("workspace.readartifact", r)
        assert nc == "TCP报文数据..."

    def test_readartifact_output_text(self):
        r = ToolResult(node_id="n1", tool="workspace.readartifact", success=True,
                       data={"output": {"text": "多行文本数据"}})
        nc = _extract_normalized_content("workspace.readartifact", r)
        assert nc == "多行文本数据"

    def test_readartifact_output_preview(self):
        r = ToolResult(node_id="n1", tool="workspace.readartifact", success=True,
                       data={"output": {"preview": "预览内容..."}})
        nc = _extract_normalized_content("workspace.readartifact", r)
        assert nc == "预览内容..."

    def test_readartifact_direct_content(self):
        r = ToolResult(node_id="n1", tool="workspace.readartifact", success=True,
                       data={"content": "直接内容"})
        nc = _extract_normalized_content("workspace.readartifact", r)
        assert nc == "直接内容"

    def test_readartifact_preview(self):
        r = ToolResult(node_id="n1", tool="workspace.readartifact", success=True,
                       data={"preview": "文件预览"})
        nc = _extract_normalized_content("workspace.readartifact", r)
        assert nc == "文件预览"

    def test_readartifact_summary(self):
        r = ToolResult(node_id="n1", tool="workspace.readartifact", success=True,
                       data={"summary": "文件摘要"})
        nc = _extract_normalized_content("workspace.readartifact", r)
        assert nc == "文件摘要"

    def test_priority_order(self):
        # output.content should win over data.content
        r = ToolResult(node_id="n1", tool="workspace.readartifact", success=True,
                       data={
                           "output": {"content": "优先级最高"},
                           "content": "被覆盖",
                       })
        nc = _extract_normalized_content("workspace.readartifact", r)
        assert nc == "优先级最高"

    def test_workspace_file_read(self):
        r = ToolResult(node_id="n1", tool="workspace.file", success=True,
                       data={"output": {"content": "文件数据"}})
        nc = _extract_normalized_content("workspace.file", r)
        assert nc == "文件数据"

    def test_exec_run_not_extracted(self):
        r = ToolResult(node_id="n1", tool="exec.run", success=True,
                       data={"output": {"content": "shell output"}})
        nc = _extract_normalized_content("exec.run", r)
        assert nc is None

    def test_non_dict_data(self):
        r = ToolResult(node_id="n1", tool="workspace.readartifact", success=True,
                       data="plain string")
        nc = _extract_normalized_content("workspace.readartifact", r)
        assert nc is None

    def test_empty_data(self):
        r = ToolResult(node_id="n1", tool="workspace.readartifact", success=True,
                       data={})
        nc = _extract_normalized_content("workspace.readartifact", r)
        assert nc is None

    def test_get_nested(self):
        d = {"a": {"b": {"c": "value"}}}
        assert _get_nested(d, "a.b.c") == "value"
        assert _get_nested(d, "a.b.x") is None
        assert _get_nested(d, "x.y.z") is None


# ============================================================================
# Integration: SPEGEngine with normalized_content in merged results
# ============================================================================

class TestMergedNormalizedContent:
    """Verify that ResultMerger.merge() includes normalized_content."""

    def _build_dag_and_run(self, tool_id, result_data):
        """Helper: build a single-node DAG and merge results."""
        from speg_engine.models import PlanNode, SPEGConfig
        from speg_engine.graph_compiler import GraphCompiler

        plan_node = PlanNode(id="n1", tool=tool_id, args={}, deps=[])
        compiler = GraphCompiler(config=SPEGConfig())
        dag = compiler.compile([plan_node])

        node_results = {
            "n1": ToolResult(node_id="n1", tool=tool_id, success=True,
                             data=result_data),
        }

        merger = ResultMerger()
        ctx = StatelessContext(workspace_id="test", session_id="s1",
                               request_id="r1", user_input="test")
        merged = merger.merge(dag, node_results, ctx)
        return merged

    def test_readartifact_creates_normalized_content(self):
        merged = self._build_dag_and_run(
            "workspace.readartifact",
            {"output": {"content": "TCP报文数据分析中..."}},
        )
        nc = merged.get("normalized_content", [])
        assert len(nc) == 1
        assert "TCP报文" in nc[0]

    def test_exec_run_no_normalized_content(self):
        merged = self._build_dag_and_run(
            "exec.run",
            {"output": {"content": "some command output"}},
        )
        nc = merged.get("normalized_content", [])
        assert len(nc) == 0


# ============================================================================
# Integration: SPEGEngine empty-plan task-intent guard
# ============================================================================

class TestEmptyPlanTaskIntentGuard:
    """Verify PLANNER_EMPTY_FOR_TASK_INTENT when planner returns empty."""

    def test_analyse_request_empty_nodes_fails(self):
        """'分析' with empty planner nodes → error, not success."""
        llm_calls = []

        def llm_mock(**kwargs):
            llm_calls.append(kwargs)
            return '{"nodes": []}'  # planner returns empty

        config = SPEGConfig()
        engine = SPEGEngine(
            config=config, llm_invoke=llm_mock,
            tool_runtime=mock.MagicMock(),
        )

        result = asyncio.run(engine.run(
            user_input="请分析这份数据",
            workspace_id="test",
        ))
        assert result.success is False
        # Check structured_errors for the error code
        structured = result.metadata.get("structured_errors", [])
        codes = [e.get("code", "") for e in structured]
        assert "PLANNER_EMPTY_FOR_TASK_INTENT" in codes

    def test_cmdb_inspection_empty_nodes_fails(self):
        """'巡检' with empty planner nodes → error."""
        llm_calls = []

        def llm_mock(**kwargs):
            llm_calls.append(kwargs)
            return '{"nodes": []}'

        config = SPEGConfig()
        engine = SPEGEngine(
            config=config, llm_invoke=llm_mock,
            tool_runtime=mock.MagicMock(),
        )

        result = asyncio.run(engine.run(
            user_input="我想对 CMDB 资产 ASBR-PE1 发起自动巡检",
            workspace_id="test",
        ))
        assert result.success is False
        structured = result.metadata.get("structured_errors", [])
        codes = [e.get("code", "") for e in structured]
        assert "PLANNER_EMPTY_FOR_TASK_INTENT" in codes

    def test_definition_question_empty_nodes_ok(self):
        """'是什么' with empty nodes → should NOT fail (not task intent)."""
        llm_calls = []

        def llm_mock(**kwargs):
            llm_calls.append(kwargs)
            return '{"nodes": []}'

        config = SPEGConfig()
        engine = SPEGEngine(
            config=config, llm_invoke=llm_mock,
            tool_runtime=mock.MagicMock(),
        )

        result = asyncio.run(engine.run(
            user_input="OSPF 是什么",
            workspace_id="test",
        ))
        # No errors expected — definition question is not task intent
        assert "PLANNER_EMPTY_FOR_TASK_INTENT" not in str(result.errors)

    def test_non_task_empty_nodes_ok(self):
        """'你好' with empty nodes → OK (not task intent)."""
        llm_calls = []

        def llm_mock(**kwargs):
            llm_calls.append(kwargs)
            return '{"nodes": []}'

        config = SPEGConfig()
        engine = SPEGEngine(
            config=config, llm_invoke=llm_mock,
            tool_runtime=mock.MagicMock(),
        )

        result = asyncio.run(engine.run(
            user_input="你好",
            workspace_id="test",
        ))
        assert "PLANNER_EMPTY_FOR_TASK_INTENT" not in str(result.errors)


# ============================================================================
# Integration: Final response validator — TASK_INCOMPLETE
# ============================================================================

class TestTaskIncompleteValidator:
    """Verify final_response validator catches incomplete responses."""

    def test_shou_dao_triggers_incomplete(self):
        """Task request + final_response='收到' → FINALIZER_TASK_INCOMPLETE."""
        llm_outputs = []

        def llm_mock(**kwargs):
            llm_outputs.append(kwargs.get("user", ""))
            # Planner returns knowledge.manage (read-only, no approval)
            if "planner" in (kwargs.get("system", "") or "").lower():
                return '{"nodes": [{"id": "n1", "tool": "knowledge.manage", "args": {"action": "search", "query": "test"}, "deps": []}]}'
            return "收到"

        tool_runtime = mock.MagicMock()
        async def mock_execute_layer(nodes, ctx, all_results):
            return {
                "n1": ToolResult(node_id="n1", tool="knowledge.manage", success=True,
                                 data={"output": "no results"}),
            }
        tool_runtime.execute_layer = mock_execute_layer

        config = SPEGConfig(enable_finalizer=True, max_llm_calls=3)
        engine = SPEGEngine(
            config=config, llm_invoke=llm_mock,
            tool_runtime=tool_runtime,
        )
        engine.register_tool("knowledge.manage", mock.AsyncMock(), description="Knowledge search")

        result = asyncio.run(engine.run(
            user_input="请分析查询结果",
            workspace_id="test",
        ))
        errors_str = str(result.errors)
        assert "FINALIZER_TASK_INCOMPLETE" in errors_str or not result.success

    def test_no_tools_executed_with_task_intent_fails(self):
        """Task request + empty plan → PLANNER_EMPTY_FOR_TASK_INTENT."""
        llm_calls = []

        def llm_mock(**kwargs):
            llm_calls.append(kwargs)
            return '{"nodes": []}'

        config = SPEGConfig()
        engine = SPEGEngine(
            config=config, llm_invoke=llm_mock,
            tool_runtime=mock.MagicMock(),
        )

        result = asyncio.run(engine.run(
            user_input="我想对 CMDB 区域「广域网」发起自动巡检",
            workspace_id="test",
        ))
        assert result.success is False
        structured = result.metadata.get("structured_errors", [])
        codes = [e.get("code", "") for e in structured]
        assert "PLANNER_EMPTY_FOR_TASK_INTENT" in codes

    def test_valid_final_response_not_flagged(self):
        """Good analysis response → no TASK_INCOMPLETE."""
        llm_outputs = []

        def llm_mock(**kwargs):
            llm_outputs.append(kwargs.get("user", ""))
            if "planner" in (kwargs.get("system", "") or "").lower():
                return '{"nodes": [{"id": "n1", "tool": "knowledge.manage", "args": {"action": "search", "query": "TCP"}, "deps": []}]}'
            return "TCP报文分析：192.168.5.12 连接 192.168.5.8:3389，三次握手完成，无异常。"

        tool_runtime = mock.MagicMock()
        async def mock_execute_layer(nodes, ctx, all_results):
            return {
                "n1": ToolResult(node_id="n1", tool="knowledge.manage", success=True,
                                 data={"output": "192.168.5.12:63028 -> 192.168.5.8:3389 SYN SYN-ACK ACK"}),
            }
        tool_runtime.execute_layer = mock_execute_layer

        config = SPEGConfig(enable_finalizer=True, max_llm_calls=3)
        engine = SPEGEngine(
            config=config, llm_invoke=llm_mock,
            tool_runtime=tool_runtime,
        )
        engine.register_tool("knowledge.manage", mock.AsyncMock(), description="Knowledge search")

        result = asyncio.run(engine.run(
            user_input="请分析这份 TCP 报文数据",
            workspace_id="test",
        ))
        assert result.success
        assert "TASK_INCOMPLETE" not in str(result.errors)
        assert "PLANNER_EMPTY_FOR_TASK_INTENT" not in str(result.errors)


# ============================================================================
# Integration: Finalizer prompt includes normalized_content
# ============================================================================

class TestFinalizerPromptNormalizedContent:
    """Verify finalizer prompt includes normalized_content when available."""

    def test_normalized_content_in_finalizer_prompt(self):
        """After knowledge.manage, finalizer prompt includes results."""
        llm_outputs = []

        def llm_mock(**kwargs):
            user = kwargs.get("user", "")
            llm_outputs.append(user)
            if "planner" in (kwargs.get("system", "") or "").lower():
                return '{"nodes": [{"id": "n1", "tool": "knowledge.manage", "args": {"action": "search", "query": "TCP"}, "deps": []}]}'
            return "基于查询结果分析，连接正常。"

        tool_runtime = mock.MagicMock()
        async def mock_execute_layer(nodes, ctx, all_results):
            return {
                "n1": ToolResult(node_id="n1", tool="knowledge.manage", success=True,
                                 data={"output": "192.168.5.12:63028 -> 192.168.5.8:3389"}),
            }
        tool_runtime.execute_layer = mock_execute_layer

        config = SPEGConfig(enable_finalizer=True, max_llm_calls=3)
        engine = SPEGEngine(
            config=config, llm_invoke=llm_mock,
            tool_runtime=tool_runtime,
        )
        engine.register_tool("knowledge.manage", mock.AsyncMock(), description="Knowledge search")

        result = asyncio.run(engine.run(
            user_input="请分析这份 TCP 报文数据",
            workspace_id="test",
        ))
        assert result.success

        # Find the finalizer prompt
        finalizer_prompts = [o for o in llm_outputs if "ORIGINAL USER REQUEST" in o and "EXECUTION RESULTS" in o]
        assert len(finalizer_prompts) >= 1, "Finalizer should have been called"
        prompt = finalizer_prompts[-1]
        assert "192.168.5.12" in prompt
