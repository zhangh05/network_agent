"""Tests for SSOT Runtime v3.14 Task Completion Contract.

Verifies that SSOT Runtime no longer returns placeholder responses ("收到", "No tools
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

from core.runtime_engine import SSOTRuntimeConfig, SSOTRuntimeEngine
from core.runtime_engine.models import StatelessContext, ExecutionNode, ExecutionDAG, ToolResult
from core.runtime_engine.engine import (
    detect_task_intent,
    plan_nodes_empty_for_task,
    _is_task_incomplete_final_response,
    validate_final_response,
    TaskIntentResult,
    FinalResponseValidatorResult,
)
from types import SimpleNamespace
from core.runtime_engine.result_merger import (
    ResultMerger,
    _extract_normalized_content,
    _get_nested,
)
from core.runtime_engine.errors import SSOTRuntimeErrorCode


# ============================================================================
# Unit: task-intent detection
# ============================================================================

class TestTaskIntentDetection:
    """detect_task_intent() standalone tests."""

    def test_analyse_has_task_intent(self):
        r = detect_task_intent("分析这个 TCP 报文数据")
        assert r.is_task is True
        # "报文" triggers pcap_analysis
        assert r.intent_type in ("analysis", "pcap_analysis")

    def test_inspect_has_task_intent(self):
        r = detect_task_intent("我想对 CMDB 资产发起自动巡检")
        assert r.is_task is True
        assert r.intent_type == "inspection"

    def test_read_file_has_task_intent(self):
        r = detect_task_intent("读取配置文件并分析结果")
        assert r.is_task is True

    def test_check_has_task_intent(self):
        r = detect_task_intent("检查设备状态")
        assert r.is_task is True

    def test_generate_report_has_task_intent(self):
        r = detect_task_intent("生成一份检查报告")
        assert r.is_task is True

    def test_summarise_has_task_intent(self):
        r = detect_task_intent("总结一下这些数据")
        assert r.is_task is True

    def test_diagnose_has_task_intent(self):
        r = detect_task_intent("诊断网络故障原因")
        assert r.is_task is True

    def test_compare_has_task_intent(self):
        r = detect_task_intent("对比两个配置")
        assert r.is_task is True

    def test_definition_question_not_task_intent(self):
        assert detect_task_intent("OSPF 是什么").is_task is False
        assert detect_task_intent("解释一下什么是 BGP").is_task is False

    def test_introduce_not_task_intent(self):
        assert detect_task_intent("介绍一下这个功能").is_task is False

    def test_greeting_not_task_intent(self):
        assert detect_task_intent("你好").is_task is False

    def test_simple_question_not_task_intent(self):
        assert detect_task_intent("今天天气怎么样").is_task is False

    def test_empty_not_task_intent(self):
        assert detect_task_intent("").is_task is False

    # Cases that look like definition but are still task intent
    def test_why_is_this_happening_is_task(self):
        r = detect_task_intent("这个截图为什么会这样")
        assert r.is_task is True

    def test_what_problem_is_this_is_task(self):
        r = detect_task_intent("帮我分析这是什么问题")
        assert r.is_task is True

    def test_read_log_what_exception_is_task(self):
        r = detect_task_intent("读取这个日志看看是什么异常")
        assert r.is_task is True

    def test_old_alias_still_works(self):
        assert plan_nodes_empty_for_task("分析数据") is True
        assert plan_nodes_empty_for_task("OSPF 是什么") is False


# ============================================================================
# Unit: incomplete response detection
# ============================================================================

class TestIncompleteResponseDetection:
    """validate_final_response() tests."""

    def test_shou_dao_incomplete(self):
        v = validate_final_response("分析数据", "收到")
        assert v.valid is False

    def test_completed_incomplete(self):
        assert validate_final_response("分析数据", "已完成").valid is False

    def test_tool_chenggong_incomplete(self):
        assert validate_final_response("分析数据", "工具调用成功").valid is False

    def test_no_tools_incomplete(self):
        assert validate_final_response("分析数据", "No tools were executed").valid is False

    def test_readartifact_completed_incomplete(self):
        assert validate_final_response("分析这个报文", "readartifact completed").valid is False

    def test_empty_response_incomplete(self):
        assert validate_final_response("分析数据", "").valid is False

    def test_real_analysis_not_incomplete(self):
        resp = "报文分析显示 TCP 连接正常，三次握手完成，无丢包。"
        assert validate_final_response("分析这个报文", resp).valid is True

    def test_non_task_input_not_checked(self):
        assert validate_final_response("你好", "收到").valid is True
        assert validate_final_response("OSPF 是什么", "").valid is True

    def test_analysis_with_placeholder_word_not_flagged(self):
        # "巡检已完成，结论如下..." contains "已完成" but has analysis → not flagged
        resp = "巡检已完成，结论如下：ASBR-PE1 状态正常，无严重告警。建议定期复查。"
        assert validate_final_response("巡检 CMDB", resp).valid is True

    def test_file_read_analysis_not_flagged(self):
        resp = "文件读取已完成，分析结论如下：TCP 连接正常，无异常报文。"
        assert validate_final_response("读取文件并分析", resp).valid is True

    def test_command_analysis_not_flagged(self):
        resp = "命令执行完成，发现以下异常：接口 eth0 存在丢包。"
        assert validate_final_response("执行命令检查", resp).valid is True

    def test_old_alias_still_works(self):
        assert _is_task_incomplete_final_response("分析数据", "收到") is True
        assert _is_task_incomplete_final_response("分析数据", "报文分析完成，连接正常。") is False


# ============================================================================
# Unit: normalized_content extraction
# ============================================================================

class TestNormalizedContentExtraction:
    """_extract_normalized_content() tests."""

    def test_readartifact_output_content(self):
        r = ToolResult(node_id="n1", tool="workspace.readartifact", success=True,
                       data={"output": {"content": "TCP报文数据..."}})
        n = SimpleNamespace(tool="workspace.readartifact", args={})
        nc = _extract_normalized_content(n, r)
        assert nc is not None
        assert nc["content"] == "TCP报文数据..."

    def test_readartifact_output_text(self):
        r = ToolResult(node_id="n1", tool="workspace.readartifact", success=True,
                       data={"output": {"text": "多行文本数据"}})
        n = SimpleNamespace(tool="workspace.readartifact", args={})
        nc = _extract_normalized_content(n, r)
        assert nc is not None
        assert nc["content"] == "多行文本数据"

    def test_readartifact_output_preview(self):
        r = ToolResult(node_id="n1", tool="workspace.readartifact", success=True,
                       data={"output": {"preview": "预览内容..."}})
        n = SimpleNamespace(tool="workspace.readartifact", args={})
        nc = _extract_normalized_content(n, r)
        assert nc is not None
        assert nc["content"] == "预览内容..."

    def test_readartifact_direct_content(self):
        r = ToolResult(node_id="n1", tool="workspace.readartifact", success=True,
                       data={"content": "直接内容"})
        n = SimpleNamespace(tool="workspace.readartifact", args={})
        nc = _extract_normalized_content(n, r)
        assert nc is not None
        assert nc["content"] == "直接内容"

    def test_readartifact_preview(self):
        r = ToolResult(node_id="n1", tool="workspace.readartifact", success=True,
                       data={"preview": "文件预览"})
        n = SimpleNamespace(tool="workspace.readartifact", args={})
        nc = _extract_normalized_content(n, r)
        assert nc is not None
        assert nc["content"] == "文件预览"

    def test_readartifact_summary(self):
        r = ToolResult(node_id="n1", tool="workspace.readartifact", success=True,
                       data={"summary": "文件摘要"})
        n = SimpleNamespace(tool="workspace.readartifact", args={})
        nc = _extract_normalized_content(n, r)
        assert nc is not None
        assert nc["content"] == "文件摘要"

    def test_priority_order(self):
        r = ToolResult(node_id="n1", tool="workspace.readartifact", success=True,
                       data={"output": {"content": "优先级最高"}, "content": "被覆盖"})
        n = SimpleNamespace(tool="workspace.readartifact", args={})
        nc = _extract_normalized_content(n, r)
        assert nc is not None
        assert nc["content"] == "优先级最高"

    def test_workspace_file_read(self):
        r = ToolResult(node_id="n1", tool="workspace.file", success=True,
                       data={"output": {"content": "文件数据"}})
        n = SimpleNamespace(tool="workspace.file", args={})
        nc = _extract_normalized_content(n, r)
        assert nc is not None
        assert nc["content"] == "文件数据"

    def test_exec_run_not_extracted(self):
        r = ToolResult(node_id="n1", tool="exec.run", success=True,
                       data={"output": {"content": "shell output"}})
        n = SimpleNamespace(tool="exec.run", args={})
        nc = _extract_normalized_content(n, r)
        assert nc is not None
        assert nc["content"] == "shell output"

    def test_non_dict_data(self):
        r = ToolResult(node_id="n1", tool="workspace.readartifact", success=True,
                       data="plain string")
        n = SimpleNamespace(tool="workspace.readartifact", args={})
        nc = _extract_normalized_content(n, r)
        assert nc is not None
        assert nc["content"] == "plain string"

    def test_empty_data(self):
        r = ToolResult(node_id="n1", tool="workspace.readartifact", success=True,
                       data={})
        n = SimpleNamespace(tool="workspace.readartifact", args={})
        nc = _extract_normalized_content(n, r)
        assert nc is None

    def test_node_args_source_path(self):
        """source_path from node.args.file."""
        r = ToolResult(node_id="n1", tool="workspace.file", success=True,
                       data={"output": {"content": "data"}})
        n = SimpleNamespace(tool="workspace.file", args={"action": "read", "file": "tcp.txt"})
        nc = _extract_normalized_content(n, r)
        assert nc is not None
        assert nc["source_path"] == "tcp.txt"
        assert nc["action"] == "read"

    def test_node_args_artifact_id(self):
        r = ToolResult(node_id="n1", tool="workspace.artifact", success=True,
                       data={"output": {"content": "artifact data"}})
        n = SimpleNamespace(tool="workspace.artifact", args={"action": "read", "artifact_id": "art_xxx"})
        nc = _extract_normalized_content(n, r)
        assert nc is not None
        assert nc["artifact_id"] == "art_xxx"

    def test_failed_tool_with_error(self):
        r = ToolResult(node_id="n1", tool="workspace.file", success=False,
                       data={}, error="permission denied")
        n = SimpleNamespace(tool="workspace.file", args={"file": "secret.txt"})
        nc = _extract_normalized_content(n, r)
        assert nc is not None
        assert "permission denied" in nc["content"]
        assert nc["success"] is False

    def test_get_nested(self):
        d = {"a": {"b": {"c": "value"}}}
        assert _get_nested(d, "a.b.c") == "value"
        assert _get_nested(d, "a.b.x") is None
        assert _get_nested(d, "x.y.z") is None


# ============================================================================
# Integration: SSOTRuntimeEngine with normalized_content in merged results
# ============================================================================

class TestMergedNormalizedContent:
    """Verify that ResultMerger.merge() includes normalized_content."""

    def _build_dag_and_run(self, tool_id, result_data):
        """Helper: build a single-node DAG and merge results."""
        from core.runtime_engine.models import PlanNode, SSOTRuntimeConfig
        from core.runtime_engine.graph_compiler import GraphCompiler

        plan_node = PlanNode(id="n1", tool=tool_id, args={}, deps=[])
        compiler = GraphCompiler(config=SSOTRuntimeConfig())
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
        assert "TCP报文" in nc[0]["content"]

    def test_exec_run_no_normalized_content(self):
        merged = self._build_dag_and_run(
            "exec.run",
            {"output": {"content": "some command output"}},
        )
        nc = merged.get("normalized_content", [])
        # exec.run IS now in _NC_TOOL_PREFIXES
        assert len(nc) == 1


# ============================================================================
# Integration: SSOTRuntimeEngine empty-plan task-intent guard
# ============================================================================

class TestEmptyPlanTaskIntentGuard:
    """Verify PLANNER_EMPTY_FOR_TASK_INTENT when planner returns empty."""

    def test_analyse_request_empty_nodes_fails(self):
        """'分析' with empty planner nodes → error, not success."""
        llm_calls = []

        def llm_mock(**kwargs):
            llm_calls.append(kwargs)
            return '{"nodes": []}'  # planner returns empty

        config = SSOTRuntimeConfig()
        engine = SSOTRuntimeEngine(
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

        config = SSOTRuntimeConfig()
        engine = SSOTRuntimeEngine(
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

        config = SSOTRuntimeConfig()
        engine = SSOTRuntimeEngine(
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

        config = SSOTRuntimeConfig()
        engine = SSOTRuntimeEngine(
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

        config = SSOTRuntimeConfig(enable_finalizer=True, max_llm_calls=3)
        engine = SSOTRuntimeEngine(
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

        config = SSOTRuntimeConfig()
        engine = SSOTRuntimeEngine(
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

        config = SSOTRuntimeConfig(enable_finalizer=True, max_llm_calls=3)
        engine = SSOTRuntimeEngine(
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

        config = SSOTRuntimeConfig(enable_finalizer=True, max_llm_calls=3)
        engine = SSOTRuntimeEngine(
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
