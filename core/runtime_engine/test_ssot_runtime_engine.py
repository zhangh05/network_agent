"""
Comprehensive tests for SSOT Runtime Engine.

Tests cover:
  - Planner: JSON parsing, error handling, edge cases
  - Graph Compiler: DAG topology, depth assignment, cycle elimination
  - DAG Validator: tool existence, args schema, dep integrity
  - Execution Engine: async parallel execution, failure isolation
  - Tool Runtime: stateless execution, dependency injection
  - Result Merger: structured output, ordering
  - Full pipeline: end-to-end integration
  - Latency model verification
"""

import asyncio
import json
import time
import pytest

from core.runtime_engine.models import (
    ExecutionDAG,
    ExecutionNode,
    ExecutionStatus,
    PlanNode,
    SSOTRuntimeConfig,
    DAGStatus,
    StatelessContext,
    ToolResult,
)
from core.runtime_engine.graph_compiler import GraphCompiler
from core.runtime_engine.dag_validator import DAGValidator
from core.runtime_engine.tool_runtime import ToolRuntime
from core.runtime_engine.execution_engine import ExecutionEngine
from core.runtime_engine.result_merger import ResultMerger
from core.runtime_engine.finalizer import Finalizer
from core.runtime_engine.planner import Planner, PLANNER_SYSTEM_PROMPT
from core.runtime_engine.plan_enrichment import enrich_plan_nodes_from_user_request


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def config():
    return SSOTRuntimeConfig()


@pytest.fixture
def sample_tool_registry():
    return {
        "exec.run": {
            "description": "Run a shell command",
            "args_schema": {
                "required": ["command"],
                "properties": {
                    "command": {"type": "string"},
                    "timeout": {"type": "number"},
                },
            },
        },
        "workspace.file": {
            "description": "Read/write workspace files",
            "args_schema": {
                "required": ["action", "path"],
                "properties": {
                    "action": {"type": "string"},
                    "path": {"type": "string"},
                },
            },
        },
        "web.manage": {
            "description": "Web search and page fetch",
            "args_schema": {
                "required": ["action"],
                "properties": {
                    "action": {"type": "string"},
                    "query": {"type": "string"},
                },
            },
        },
        "data.manage": {
            "description": "Data processing",
            "args_schema": {
                "required": ["action"],
                "properties": {
                    "action": {"type": "string"},
                    "data": {"type": "object"},
                },
            },
        },
        "knowledge.manage": {
            "description": "Knowledge base search",
            "args_schema": {
                "required": ["action"],
                "properties": {
                    "action": {"type": "string"},
                    "query": {"type": "string"},
                },
            },
        },
        "device.manage": {
            "description": "Device asset management (destructive operations)",
            "args_schema": {
                "required": ["action"],
                "properties": {"action": {"type": "string"}},
            },
            "unsafe_tags": ["destructive"],
        },
    }


class TestEngineFailureFallbacks:
    @pytest.mark.asyncio
    async def test_top_level_exception_does_not_default_workspace(self, config):
        from core.runtime_engine.engine import SSOTRuntimeEngine

        engine = SSOTRuntimeEngine(config=config)

        async def boom(*args, **kwargs):
            raise RuntimeError("synthetic crash")

        engine._run_internal = boom

        result = await engine.run(
            "触发异常",
            workspace_id="",
            session_id="",
        )

        assert result.success is False
        assert result.metadata["workspace_id"] == ""
        assert result.metadata["session_id"] == "error"
        assert "synthetic crash" in "; ".join(result.errors)
        assert result.final_response
        assert "运行时异常" in result.final_response

    @pytest.mark.asyncio
    async def test_fast_path_llm_failure_returns_user_visible_message(self, config):
        from core.runtime_engine.engine import SSOTRuntimeEngine

        def failing_llm(**kwargs):
            raise RuntimeError("provider down")

        engine = SSOTRuntimeEngine(config=config, llm_invoke=failing_llm)

        result = await engine.run("你好", workspace_id="ws_fast", session_id="s1")

        assert result.success is False
        assert result.final_response
        assert "暂时无法生成回复" in result.final_response
        assert any("provider down" in err for err in result.errors)


# ============================================================================
# Graph Compiler Tests
# ============================================================================

class TestGraphCompiler:
    """Test deterministic DAG compilation from planner JSON."""

    def test_empty_graph(self, config):
        compiler = GraphCompiler(config)
        dag = compiler.compile([])
        assert dag.total_nodes == 0
        assert dag.max_depth == 0

    def test_single_node(self, config):
        compiler = GraphCompiler(config)
        nodes = [PlanNode(id="n1", tool="exec.run", args={"command": "ls"})]
        dag = compiler.compile(nodes)
        assert dag.total_nodes == 1
        assert dag.max_depth == 0
        assert dag.nodes[0].depth == 0

    def test_linear_chain(self, config):
        """n1 → n2 → n3 (depth 0,1,2)"""
        compiler = GraphCompiler(config)
        nodes = [
            PlanNode(id="n1", tool="exec.run", args={"command": "ls"}),
            PlanNode(id="n2", tool="workspace.file", args={"action": "read", "path": "/f"}, deps=["n1"]),
            PlanNode(id="n3", tool="data.manage", args={"action": "csv"}, deps=["n2"]),
        ]
        dag = compiler.compile(nodes)
        assert dag.total_nodes == 3
        assert dag.max_depth == 2
        assert dag.nodes[0].depth == 0  # n1
        assert dag.nodes[1].depth == 1  # n2
        assert dag.nodes[2].depth == 2  # n3

    def test_parallel_nodes(self, config):
        """n1, n2 are independent → both at depth 0"""
        compiler = GraphCompiler(config)
        nodes = [
            PlanNode(id="n1", tool="exec.run", args={"command": "ls"}),
            PlanNode(id="n2", tool="web.manage", args={"action": "search", "query": "test"}),
        ]
        dag = compiler.compile(nodes)
        assert dag.total_nodes == 2
        assert dag.max_depth == 0
        assert all(n.depth == 0 for n in dag.nodes)

    def test_diamond_dependency(self, config):
        """n1 → n2, n1 → n3, n2 → n4, n3 → n4"""
        compiler = GraphCompiler(config)
        nodes = [
            PlanNode(id="n1", tool="exec.run", args={"command": "fetch"}),
            PlanNode(id="n2", tool="workspace.file", args={"action": "read", "path": "a"}, deps=["n1"]),
            PlanNode(id="n3", tool="web.manage", args={"action": "search", "query": "x"}, deps=["n1"]),
            PlanNode(id="n4", tool="data.manage", args={"action": "csv"}, deps=["n2", "n3"]),
        ]
        dag = compiler.compile(nodes)
        assert dag.total_nodes == 4
        assert dag.max_depth == 2
        # n2 and n3 at same depth (1), n4 at depth 2
        assert dag.nodes[1].depth == 1  # n2
        assert dag.nodes[2].depth == 1  # n3
        assert dag.nodes[3].depth == 2  # n4

    def test_missing_dependency_error(self, config):
        compiler = GraphCompiler(config)
        nodes = [
            PlanNode(id="n1", tool="exec.run", args={}, deps=["nonexistent"]),
        ]
        with pytest.raises(ValueError, match="depends on"):
            compiler.compile(nodes)

    def test_layers_are_built(self, config):
        compiler = GraphCompiler(config)
        nodes = [
            PlanNode(id="n1", tool="exec.run", args={"command": "a"}),
            PlanNode(id="n2", tool="exec.run", args={"command": "b"}),
        ]
        dag = compiler.compile(nodes)
        assert 0 in dag.layers
        assert len(dag.layers[0]) == 2


# ============================================================================
# DAG Validator Tests
# ============================================================================

class TestDAGValidator:

    def test_valid_dag(self, config, sample_tool_registry):
        validator = DAGValidator(config, sample_tool_registry)
        nodes = [
            ExecutionNode(id="n1", tool="exec.run", args={"command": "ls"}, depth=0),
            ExecutionNode(id="n2", tool="workspace.file", args={"action": "read", "path": "/f"}, depth=1, deps=["n1"]),
        ]
        dag = ExecutionDAG(nodes=nodes, total_nodes=2, max_depth=1)
        dag = validator.validate(dag)
        assert dag.is_valid

    def test_unknown_tool(self, config, sample_tool_registry):
        validator = DAGValidator(config, sample_tool_registry)
        nodes = [
            ExecutionNode(id="n1", tool="nonexistent.tool", args={}, depth=0),
        ]
        dag = ExecutionDAG(nodes=nodes, total_nodes=1, max_depth=0)
        dag = validator.validate(dag)
        assert not dag.is_valid
        assert dag.status == DAGStatus.INVALID_TOOL

    def test_missing_required_args(self, config, sample_tool_registry):
        validator = DAGValidator(config, sample_tool_registry)
        nodes = [
            ExecutionNode(id="n1", tool="exec.run", args={}, depth=0),  # missing "command"
        ]
        dag = ExecutionDAG(nodes=nodes, total_nodes=1, max_depth=0)
        dag = validator.validate(dag)
        assert not dag.is_valid

    def test_max_nodes_limit(self, config, sample_tool_registry):
        config.max_nodes = 2
        validator = DAGValidator(config, sample_tool_registry)
        nodes = [
            ExecutionNode(id="n1", tool="exec.run", args={"command": "a"}, depth=0),
            ExecutionNode(id="n2", tool="exec.run", args={"command": "b"}, depth=0),
            ExecutionNode(id="n3", tool="exec.run", args={"command": "c"}, depth=0),
        ]
        dag = ExecutionDAG(nodes=nodes, total_nodes=3, max_depth=0)
        dag = validator.validate(dag)
        assert not dag.is_valid

    def test_destructive_tool_rejected(self, config, sample_tool_registry):
        validator = DAGValidator(config, sample_tool_registry)
        nodes = [
            ExecutionNode(id="n1", tool="device.manage", args={"action": "delete"}, depth=0),
        ]
        dag = ExecutionDAG(nodes=nodes, total_nodes=1, max_depth=0)
        dag = validator.validate(dag)
        assert not dag.is_valid
        assert dag.status == DAGStatus.UNSAFE_PATH


# ============================================================================
# Tool Runtime Tests
# ============================================================================

class TestToolRuntime:

    @pytest.mark.asyncio
    async def test_execute_simple_tool(self, config):
        runtime = ToolRuntime(config)

        async def my_handler(args):
            return f"result: {args.get('msg', '')}"

        runtime.register("test.echo", my_handler)

        node = ExecutionNode(id="t1", tool="test.echo", args={"msg": "hello"})
        from core.runtime_engine.models import StatelessContext
        ctx = StatelessContext(
            workspace_id="ws", session_id="s1", request_id="r1",
            user_input="test",
        )

        result = await runtime.execute_node(node, ctx, {})
        assert result.success
        assert result.data == "result: hello"

    @pytest.mark.asyncio
    async def test_unknown_tool(self, config):
        runtime = ToolRuntime(config)
        node = ExecutionNode(id="t1", tool="no.such.tool", args={})
        from core.runtime_engine.models import StatelessContext
        ctx = StatelessContext(
            workspace_id="ws", session_id="s1", request_id="r1",
            user_input="test",
        )

        result = await runtime.execute_node(node, ctx, {})
        assert not result.success
        assert "no registered handler" in result.error

    @pytest.mark.asyncio
    async def test_parallel_layer_execution(self, config):
        runtime = ToolRuntime(config)

        async def sleep_handler(args):
            delay = args.get("delay", 0.01)
            await asyncio.sleep(delay)
            return f"done after {delay}s"

        runtime.register("test.sleep", sleep_handler)

        nodes = [
            ExecutionNode(id="a", tool="test.sleep", args={"delay": 0.05}),
            ExecutionNode(id="b", tool="test.sleep", args={"delay": 0.05}),
            ExecutionNode(id="c", tool="test.sleep", args={"delay": 0.05}),
        ]
        from core.runtime_engine.models import StatelessContext
        ctx = StatelessContext(
            workspace_id="ws", session_id="s1", request_id="r1",
            user_input="test",
        )

        t0 = time.monotonic()
        results = await runtime.execute_layer(nodes, ctx, {})
        elapsed = time.monotonic() - t0

        # All 3 ran in parallel → total < 0.15s (not 0.15s * 3)
        assert elapsed < 0.15
        assert len(results) == 3
        assert all(r.success for r in results.values())

    @pytest.mark.asyncio
    async def test_dependency_injection(self, config):
        runtime = ToolRuntime(config)

        runtime.register("test.adder", lambda args: args.get("a", 0) + args.get("b", 0))

        node = ExecutionNode(id="calc", tool="test.adder", args={"a": "$dep.fetch.data", "b": 3})

        from core.runtime_engine.models import StatelessContext
        ctx = StatelessContext(
            workspace_id="ws", session_id="s1", request_id="r1",
            user_input="test",
        )

        dep_results = {
            "fetch": ToolResult(node_id="fetch", tool="web.manage", success=True, data=7),
        }

        result = await runtime.execute_node(node, ctx, dep_results)
        assert result.success
        assert result.data == 10  # 7 + 3


# ============================================================================
# Execution Engine Tests
# ============================================================================

class TestExecutionEngine:

    @pytest.mark.asyncio
    async def test_full_dag_execution(self, config):
        runtime = ToolRuntime(config)

        async def echo(args):
            await asyncio.sleep(0.01)
            return f"echo: {args.get('text', '')}"

        runtime.register("test.echo", echo)

        engine = ExecutionEngine(config, runtime)

        nodes = [
            ExecutionNode(id="n1", tool="test.echo", args={"text": "hello"}, depth=0),
            ExecutionNode(id="n2", tool="test.echo", args={"text": "world"}, depth=0),
        ]
        dag = ExecutionDAG(
            nodes=nodes,
            layers={0: nodes},
            total_nodes=2,
            max_depth=0,
        )

        from core.runtime_engine.models import StatelessContext
        ctx = StatelessContext(
            workspace_id="ws", session_id="s1", request_id="r1",
            user_input="test",
        )

        results = await engine.execute(dag, ctx)
        assert len(results) == 2
        assert results["n1"].success
        assert results["n2"].success
        assert results["n1"].data == "echo: hello"
        assert results["n2"].data == "echo: world"

    @pytest.mark.asyncio
    async def test_failure_isolation(self, config):
        """Failed nodes should not block sibling execution."""
        runtime = ToolRuntime(config)

        async def flaky(args):
            if args.get("fail", False):
                raise RuntimeError("intentional failure")
            return "ok"

        runtime.register("test.flaky", flaky)

        engine = ExecutionEngine(config, runtime)

        nodes = [
            ExecutionNode(id="bad", tool="test.flaky", args={"fail": True}, depth=0),
            ExecutionNode(id="good", tool="test.flaky", args={"fail": False}, depth=0),
        ]
        dag = ExecutionDAG(
            nodes=nodes,
            layers={0: nodes},
            total_nodes=2,
            max_depth=0,
        )

        from core.runtime_engine.models import StatelessContext
        ctx = StatelessContext(
            workspace_id="ws", session_id="s1", request_id="r1",
            user_input="test",
        )

        results = await engine.execute(dag, ctx)
        assert len(results) == 2
        assert not results["bad"].success
        assert results["good"].success
        assert results["good"].data == "ok"

    @pytest.mark.asyncio
    async def test_retry_once(self, config):
        """A failing idempotent read-only node gets exactly 1 retry.

        v3.10: uses ``knowledge.manage`` (a BUILTIN_CONTRACTS entry
        with idempotent=True, side_effect=read, max_retries=1) so
        the ToolRetryPolicy allows the retry.  The old synthetic
        ``test.recoverable`` tool is no longer used because it has no
        contract and the policy correctly treats unknown tools as
        non-retryable.
        """
        runtime = ToolRuntime(config)
        call_count = {"count": 0}

        async def fail_once_then_ok(args):
            call_count["count"] += 1
            if call_count["count"] == 1:
                raise RuntimeError("first call fails")
            return "recovered"

        runtime.register("knowledge.manage", fail_once_then_ok)

        engine = ExecutionEngine(config, runtime)

        nodes = [
            ExecutionNode(id="r1", tool="knowledge.manage",
                          args={"action": "search"}, depth=0),
        ]
        dag = ExecutionDAG(
            nodes=nodes, layers={0: nodes}, total_nodes=1, max_depth=0,
        )

        from core.runtime_engine.models import StatelessContext
        ctx = StatelessContext(
            workspace_id="ws", session_id="s1", request_id="r1",
            user_input="test",
        )

        results = await engine.execute(dag, ctx)
        assert results["r1"].success
        assert results["r1"].data == "recovered"
        assert results["r1"].retry_count == 1
        assert call_count["count"] == 2


# ============================================================================
# Result Merger Tests
# ============================================================================

class TestResultMerger:

    def test_merge_success(self, config):
        merger = ResultMerger()
        nodes = [
            ExecutionNode(id="n1", tool="exec.run", args={}, depth=0),
            ExecutionNode(id="n2", tool="web.manage", args={}, depth=0),
        ]
        dag = ExecutionDAG(nodes=nodes, total_nodes=2, max_depth=0)

        node_results = {
            "n1": ToolResult(node_id="n1", tool="exec.run", success=True, data="output1"),
            "n2": ToolResult(node_id="n2", tool="web.manage", success=True, data="output2"),
        }

        from core.runtime_engine.models import StatelessContext
        ctx = StatelessContext(
            workspace_id="ws", session_id="s1", request_id="r1",
            user_input="test",
        )

        merged = merger.merge(dag, node_results, ctx)
        assert merged["total_nodes"] == 2
        assert merged["success_count"] == 2
        assert merged["failure_count"] == 0
        assert "exec" in merged["results_by_category"]
        assert "web" in merged["results_by_category"]
        assert merged["all_results"]["n1"]["data"] == "output1"

    def test_merge_preserves_retry_provenance(self, config):
        merger = ResultMerger()
        nodes = [
            ExecutionNode(id="n1", tool="knowledge.manage", args={"action": "search"}, depth=0),
        ]
        dag = ExecutionDAG(nodes=nodes, total_nodes=1, max_depth=0)
        node_results = {
            "n1": ToolResult(
                node_id="n1",
                tool="knowledge.manage",
                success=True,
                data={"ok": True},
                retry_count=1,
            ),
        }
        ctx = StatelessContext(
            workspace_id="ws",
            session_id="s1",
            request_id="r1",
            user_input="search",
            extras={
                "retry_summary": {
                    "retry_attempts": 1,
                    "retried_nodes": ["n1"],
                    "retry_succeeded": 1,
                    "retry_failed": 0,
                    "retry_blocked": 0,
                },
                "retry_events": [{"tool_id": "knowledge.manage", "retry_allowed": True}],
            },
        )

        merged = merger.merge(dag, node_results, ctx)

        assert merged["retry_summary"]["retry_attempts"] == 1
        assert merged["retry_events"][0]["tool_id"] == "knowledge.manage"

    def test_merge_extracts_tracking_provenance(self, config):
        merger = ResultMerger()
        nodes = [
            ExecutionNode(id="n1", tool="inspection.manage", args={"action": "run"}, depth=0),
        ]
        dag = ExecutionDAG(nodes=nodes, total_nodes=1, max_depth=0)
        tracking = {
            "kind": "long_task",
            "domain": "inspection",
            "task_id": "ins_abc",
            "status": "running",
            "done": False,
            "policy": {"mode": "medium"},
            "progress": {"done_devices": 2, "total_devices": 6, "percent": 33},
            "summary": {"task_id": "ins_abc", "status": "running", "succeeded_devices": 2},
            "next_poll_seconds": 10,
            "suggested_next_action": "poll_get",
        }
        node_results = {
            "n1": ToolResult(
                node_id="n1",
                tool="inspection.manage",
                success=True,
                data={"ok": True, "output": {"tracking": tracking}},
            ),
        }
        ctx = StatelessContext("ws", "s1", "r1", "巡检")

        merged = merger.merge(dag, node_results, ctx)

        assert merged["tracking_summary"]["task_id"] == "ins_abc"
        assert merged["tracking_summary"]["kind"] == "long_task"
        assert merged["tracking_summary"]["domain"] == "inspection"
        assert merged["tracking_summary"]["status"] == "running"
        assert merged["tracking_summary"]["progress"]["percent"] == 33
        assert ctx.extras["tracking_summary"]["task_id"] == "ins_abc"

    def test_merge_extracts_web_weather_content(self, config):
        merger = ResultMerger()
        nodes = [
            ExecutionNode(id="n1", tool="web.manage", args={"action": "weather"}, depth=0),
        ]
        dag = ExecutionDAG(nodes=nodes, total_nodes=1, max_depth=0)
        node_results = {
            "n1": ToolResult(
                node_id="n1",
                tool="web.manage",
                success=True,
                data={
                    "ok": True,
                    "output": {
                        "results_markdown": "上海未来十天天气\\n- 2026-07-03 晴",
                        "forecast_daily": [{"date": "2026-07-03"}],
                    },
                },
            )
        }
        ctx = StatelessContext("ws", "s1", "r1", "查看未来十天上海天气")

        merged = merger.merge(dag, node_results, ctx)

        assert merged["normalized_content"]
        assert "上海未来十天" in merged["normalized_content"][0]["content"]


# ============================================================================
# Planner Tests
# ============================================================================

class TestPlanner:

    def test_parse_valid_json(self, config):
        """Planner correctly parses valid JSON output."""
        mock_json = json.dumps({
            "nodes": [
                {"id": "n1", "tool": "exec.run", "args": {"command": "ls"}, "deps": []},
                {"id": "n2", "tool": "web.manage", "args": {"action": "search", "query": "x"}, "deps": ["n1"]},
            ]
        })

        def mock_llm(**kwargs):
            return mock_json

        registry = {
            "exec.run": {"description": "Run commands", "args_schema": {}},
            "web.manage": {"description": "Web search", "args_schema": {}},
        }

        planner = Planner(config, registry, mock_llm)

        from core.runtime_engine.models import StatelessContext
        ctx = StatelessContext(
            workspace_id="ws", session_id="s1", request_id="r1",
            user_input="do it",
        )

        nodes = planner.plan(ctx)
        assert len(nodes) == 2
        assert nodes[0].id == "n1"
        assert nodes[0].tool == "exec.run"
        assert nodes[1].deps == ["n1"]

    def test_plan_enrichment_converts_weather_search_to_weather(self, config):
        nodes = [
            PlanNode(
                id="n0",
                tool="web.manage",
                args={"action": "search", "query": "上海 10 day weather forecast"},
                deps=[],
            )
        ]
        events = enrich_plan_nodes_from_user_request(nodes, "你好，查看未来十天上海天气")

        assert nodes[0].args["action"] == "weather"
        assert nodes[0].args["days"] == 10
        assert nodes[0].args["location"] == "上海"
        assert events[0].reason == "weather_request_should_use_structured_weather"

    def test_plan_enrichment_adds_inspection_launcher(self, config):
        nodes = [
            PlanNode(
                id="n0",
                tool="device.manage",
                args={"action": "list", "search": "ASBR-PE1"},
                deps=[],
            )
        ]
        events = enrich_plan_nodes_from_user_request(nodes, "你将对 CMDB 资产「ASBR-PE1」 发起自动巡检。")

        assert [n.tool for n in nodes] == ["device.manage", "inspection.manage"]
        assert nodes[1].args == {"action": "run", "scope": {"search": "ASBR-PE1", "limit": 1}}
        assert events[-1].reason == "inspection_request_requires_launcher"
        assert nodes[1].deps == ["n0"]

    def test_empty_nodes(self, config):
        """Planner can return empty nodes list for simple questions."""

        def mock_llm(**kwargs):
            return '{"nodes": []}'

        planner = Planner(config, {}, mock_llm)

        from core.runtime_engine.models import StatelessContext
        ctx = StatelessContext(
            workspace_id="ws", session_id="s1", request_id="r1",
            user_input="hello",
        )

        nodes = planner.plan(ctx)
        assert nodes == []

    def test_invalid_json_rejected(self, config):
        """Planner raises on invalid JSON."""

        def mock_llm(**kwargs):
            return "not json at all"

        planner = Planner(config, {}, mock_llm)

        from core.runtime_engine.models import StatelessContext
        ctx = StatelessContext(
            workspace_id="ws", session_id="s1", request_id="r1",
            user_input="test",
        )

        with pytest.raises(ValueError, match="not valid JSON"):
            planner.plan(ctx)

    def test_markdown_fence_stripped(self, config):
        """Planner strips ``` fences from LLM output."""
        mock_json = json.dumps({
            "nodes": [{"id": "n1", "tool": "exec.run", "args": {"command": "ls"}, "deps": []}]
        })

        def mock_llm(**kwargs):
            return f"```json\n{mock_json}\n```"

        registry = {"exec.run": {"description": "", "args_schema": {}}}
        planner = Planner(config, registry, mock_llm)

        from core.runtime_engine.models import StatelessContext
        ctx = StatelessContext(
            workspace_id="ws", session_id="s1", request_id="r1",
            user_input="test",
        )

        nodes = planner.plan(ctx)
        assert len(nodes) == 1
        assert nodes[0].id == "n1"

    def test_missing_tool_field(self, config):
        """Planner raises on missing 'tool' field."""

        def mock_llm(**kwargs):
            return '{"nodes": [{"id": "n1", "args": {}}]}'

        planner = Planner(config, {}, mock_llm)

        from core.runtime_engine.models import StatelessContext
        ctx = StatelessContext(
            workspace_id="ws", session_id="s1", request_id="r1",
            user_input="test",
        )

        from core.runtime_engine.planner import SchemaValidationError
        with pytest.raises(SchemaValidationError, match="must be non-empty"):
            planner.plan(ctx)


# ============================================================================
# Finalizer Tests
# ============================================================================

class TestFinalizer:

    def test_default_response_no_llm(self, config):
        config.enable_finalizer = False
        finalizer = Finalizer(config, lambda **kw: "unused")

        merged = {
            "total_nodes": 2,
            "success_count": 2,
            "failure_count": 0,
            "results_by_category": {
                "exec": [
                    {"node_id": "n1", "tool": "exec.run", "success": True, "data": "result1", "error": None, "latency_ms": 10},
                ],
            },
            "all_results": {},
        }

        from core.runtime_engine.models import StatelessContext
        ctx = StatelessContext(
            workspace_id="ws", session_id="s1", request_id="r1",
            user_input="test",
        )

        response = asyncio.run(finalizer.finalize(ctx, merged))
        assert "exec" in response
        assert "result1" in response

    def test_finalizer_prompt_contains_authoritative_retry_provenance(self, config):
        finalizer = Finalizer(config, lambda **kw: "unused")
        ctx = StatelessContext(
            workspace_id="ws",
            session_id="s1",
            request_id="r1",
            user_input="为啥失败了",
        )
        merged = {
            "total_nodes": 1,
            "success_count": 1,
            "failure_count": 0,
            "results_by_category": {},
            "all_results": {},
            "normalized_content": [],
            "retry_summary": {
                "retry_attempts": 0,
                "retried_nodes": [],
                "retry_succeeded": 0,
                "retry_failed": 0,
                "retry_blocked": 1,
            },
            "retry_events": [
                {
                    "tool_id": "inspection.manage",
                    "retry_allowed": False,
                    "reason": "budget_exceeded",
                    "final_status": "blocked",
                },
            ],
        }

        prompt = finalizer._build_finalizer_prompt(ctx, merged)

        assert "RETRY PROVENANCE" in prompt
        assert '"retry_attempts": 0' in prompt
        assert "do NOT say the system retried" in prompt

    def test_finalizer_prompt_contains_tracking_provenance(self, config):
        finalizer = Finalizer(config, lambda **kw: "unused")
        ctx = StatelessContext(
            workspace_id="ws",
            session_id="s1",
            request_id="r1",
            user_input="跟踪巡检",
        )
        merged = {
            "total_nodes": 1,
            "success_count": 1,
            "failure_count": 0,
            "results_by_category": {},
            "all_results": {},
            "normalized_content": [],
            "tracking_summary": {
                "task_id": "ins_abc",
                "status": "running",
                "done": False,
            },
            "tracking_events": [{"tool": "inspection.manage"}],
        }

        prompt = finalizer._build_finalizer_prompt(ctx, merged)

        assert "TRACKING PROVENANCE" in prompt
        assert '"task_id": "ins_abc"' in prompt
        assert "running or pending" in prompt


# ============================================================================
# Full Pipeline Integration Test
# ============================================================================

class TestSSOTRuntimePipeline:

    @pytest.mark.asyncio
    async def test_no_tool_plan_returns_clean_result(self, config):
        """Planner may decide no tools are needed; result assembly must not crash."""
        from core.runtime_engine.engine import SSOTRuntimeEngine

        config.enable_finalizer = False

        engine = SSOTRuntimeEngine(
            config=config,
            llm_invoke=lambda **kwargs: '{"nodes": []}',
            tool_registry={},
        )

        result = await engine.run("你好")

        assert result.success
        assert result.node_success_count == 0
        assert result.node_failure_count == 0
        assert result.metadata["used_tools"] is False
        assert result.metadata["tool_calls"] == 0

    @pytest.mark.asyncio
    async def test_ambiguous_login_command_asks_clarification_without_planner(self, config):
        """Underspecified login/command requests should ask, not expose planner internals."""
        from core.runtime_engine.engine import SSOTRuntimeEngine

        config.enable_finalizer = False
        llm_calls = 0

        def mock_llm(**kwargs):
            nonlocal llm_calls
            llm_calls += 1
            return '{"nodes": []}'

        engine = SSOTRuntimeEngine(
            config=config,
            llm_invoke=mock_llm,
            tool_registry={"exec.run": {"description": "Run shell", "args_schema": {}}},
        )

        result = await engine.run("你登录刷命令")

        assert result.success
        assert llm_calls == 0
        assert result.node_success_count == 0
        assert result.metadata["planner_skipped"] is True
        assert result.metadata["requires_clarification"] is True
        assert "目标设备" in result.final_response
        assert "要执行的命令" in result.final_response
        assert "Planner failed" not in result.final_response

    def test_command_clarification_does_not_block_specific_device_goal(self):
        from core.runtime_engine.engine import (
            build_operational_clarification,
            detect_task_intent,
        )

        text = "登录并查看测试服务器_1设备的IP地址和内核"
        assert build_operational_clarification(text, detect_task_intent(text)) is None

    def test_query_loop_empty_final_fallback_is_actionable(self, config):
        from core.runtime_engine.query_loop import QueryLoop, StreamingToolResult

        class RuntimeStub:
            def has_tool(self, name):
                return name == "inspection.manage"

        loop = QueryLoop(
            config=config,
            tool_registry={"inspection.manage": {"description": "Inspection"}},
            tool_runtime=RuntimeStub(),
        )
        ctx = StatelessContext(
            workspace_id="default",
            session_id="s1",
            request_id="r1",
            user_input="对 CMDB 资产「CE2」 发起自动巡检。",
        )

        text = loop._build_tool_result_fallback(ctx, [
            StreamingToolResult(
                tool_name="device.manage",
                call_id="c1",
                output={"ok": True, "summary": "device found"},
                ok=True,
            ),
            StreamingToolResult(
                tool_name="inspection",
                call_id="c2",
                output={"ok": False, "summary": "Tool not found: inspection"},
                ok=False,
                error="Tool not found: inspection",
            ),
        ])

        assert "工具调用：成功 1 个，失败 1 个" in text
        assert "`inspection`" in text
        assert "应使用 `inspection.manage`" in text
        assert "工具执行完成" not in text

    @pytest.mark.asyncio
    async def test_query_loop_uses_injected_llm_and_budget_counter(self, config):
        """QueryLoop must use the engine-provided LLM adapter and SSOT budget."""
        from core.runtime_engine.budget_controller import BudgetController
        from core.runtime_engine.query_loop import QueryLoop

        calls = {"count": 0}

        def fake_llm(**kwargs):
            calls["count"] += 1
            assert kwargs["system"]
            assert "<current_user_request>\n解释一下" in kwargs["user"]
            assert kwargs["extra"]["stream_scope"] == "planner"
            assert kwargs["extra"]["stream_to_user"] is False
            return "这是直接说明"

        class RuntimeStub:
            def has_tool(self, name):
                return False

            def invoke_raw(self, tool_id, args):
                raise AssertionError("no tools should execute")

        budget = BudgetController(config)
        loop = QueryLoop(
            config=config,
            tool_registry={},
            tool_runtime=RuntimeStub(),
            llm_invoke=fake_llm,
        )
        ctx = StatelessContext("default", "s1", "r1", "解释一下")

        result = await loop.run(ctx, budget, metrics=None)

        assert result.final_response == "这是直接说明"
        assert result.llm_calls == 1
        assert budget.llm_calls == 1
        assert calls["count"] == 1

    @pytest.mark.asyncio
    async def test_query_loop_runs_injected_plan_json_without_old_dag(self, config):
        """Injected legacy planner JSON is absorbed by QueryLoop, not old DAG code."""
        from core.runtime_engine.budget_controller import BudgetController
        from core.runtime_engine.query_loop import QueryLoop

        config.enable_finalizer = False
        calls = {"llm": 0, "tool": 0}

        def fake_llm(**kwargs):
            calls["llm"] += 1
            return json.dumps({
                "nodes": [
                    {
                        "id": "read_status",
                        "tool": "system.manage",
                        "args": {"action": "health"},
                    }
                ]
            })

        class RuntimeStub:
            def has_tool(self, name):
                return name == "system.manage"

            def invoke_raw(self, tool_id, args):
                calls["tool"] += 1
                assert tool_id == "system.manage"
                assert args == {"action": "health"}
                return {"ok": True, "summary": "healthy"}

        loop = QueryLoop(
            config=config,
            tool_registry={
                "system.manage": {
                    "description": "System diagnostics",
                    "args_schema": {
                        "required": ["action"],
                        "properties": {"action": {"type": "string"}},
                    },
                }
            },
            tool_runtime=RuntimeStub(),
            llm_invoke=fake_llm,
        )

        result = await loop.run(
            StatelessContext("default", "s1", "r1", "检查系统健康"),
            BudgetController(config),
            metrics=None,
        )

        assert calls == {"llm": 1, "tool": 1}
        assert result.llm_calls == 1
        assert result.total_tool_calls == 1
        assert result.tool_results[0].ok is True
        assert "工具调用：成功 1 个，失败 0 个" in result.final_response

    @pytest.mark.asyncio
    async def test_query_loop_returns_validation_error_to_llm_then_executes_correction(self, config):
        """A malformed tool call is feedback, not a terminal task failure."""
        from core.runtime_engine.budget_controller import BudgetController
        from core.runtime_engine.query_loop import QueryLoop

        calls = {"llm": 0, "tool": 0}

        def fake_llm(**kwargs):
            calls["llm"] += 1
            if calls["llm"] == 1:
                return json.dumps({
                    "nodes": [{
                        "id": "health_bad",
                        "tool": "system.manage",
                        "args": {},
                    }]
                })
            if calls["llm"] == 2:
                assert "MISSING_REQUIRED_ARG" in kwargs["user"]
                assert "tool_call_id=health_bad" in kwargs["user"]
                assert '"retryable":true' in kwargs["user"]
                assert '"executed":false' in kwargs["user"]
                return json.dumps({
                    "nodes": [{
                        "id": "health_fixed",
                        "tool": "system.manage",
                        "args": {"action": "health"},
                    }]
                })
            return "系统健康检查已完成。"

        class RuntimeStub:
            def has_tool(self, name):
                return name == "system.manage"

            def invoke_raw(self, tool_id, args):
                calls["tool"] += 1
                assert args == {"action": "health"}
                return {"ok": True, "summary": "healthy"}

        loop = QueryLoop(
            config=config,
            tool_registry={
                "system.manage": {
                    "description": "System diagnostics",
                    "args_schema": {
                        "required": ["action"],
                        "properties": {
                            "action": {"type": "string", "enum": ["health"]},
                        },
                    },
                }
            },
            tool_runtime=RuntimeStub(),
            llm_invoke=fake_llm,
        )
        result = await loop.run(
            StatelessContext("default", "s1", "r1", "检查系统健康"),
            BudgetController(config),
            metrics=None,
        )

        assert result.final_response == "系统健康检查已完成。"
        assert calls == {"llm": 3, "tool": 1}
        assert result.metrics["validation_corrections"] == 1
        assert result.tool_results[0].ok is False
        assert result.tool_results[1].ok is True

    @pytest.mark.asyncio
    async def test_query_loop_bounds_repeated_validation_corrections(self, config):
        """A model that keeps emitting bad args cannot consume the full loop."""
        from core.runtime_engine.budget_controller import BudgetController
        from core.runtime_engine.query_loop import QueryLoop

        calls = {"llm": 0, "tool": 0}

        def fake_llm(**kwargs):
            calls["llm"] += 1
            return json.dumps({
                "nodes": [{
                    "id": f"bad_{calls['llm']}",
                    "tool": "system.manage",
                    "args": {},
                }]
            })

        class RuntimeStub:
            def has_tool(self, name):
                return name == "system.manage"

            def invoke_raw(self, tool_id, args):
                calls["tool"] += 1
                raise AssertionError("invalid calls must never reach executor")

        loop = QueryLoop(
            config=config,
            tool_registry={"system.manage": {"description": "System diagnostics"}},
            tool_runtime=RuntimeStub(),
            llm_invoke=fake_llm,
        )
        result = await loop.run(
            StatelessContext("default", "s1", "r1", "检查系统健康"),
            BudgetController(config),
            metrics=None,
        )

        assert result.error == "validation_correction_exhausted"
        assert calls == {"llm": 4, "tool": 0}
        assert result.metrics["validation_corrections"] == 4

    def test_query_loop_tracking_polls_are_not_provider_tool_messages(self, config):
        """Internal get polls must not create unmatched tool_call_id messages."""
        from agent.llm.schemas import LLMMessage, LLMToolCall
        from core.runtime_engine.query_loop import QueryLoop, StreamingToolResult

        class RuntimeStub:
            def has_tool(self, name):
                return name == "inspection.manage"

        loop = QueryLoop(
            config=config,
            tool_registry={"inspection.manage": {"description": "Inspection"}},
            tool_runtime=RuntimeStub(),
        )
        base_messages = [
            LLMMessage(role="system", content="system"),
            LLMMessage(role="user", content="run inspection"),
        ]
        original_call = LLMToolCall(
            id="call_1",
            name="inspection.manage",
            arguments={"action": "run"},
        )
        messages = loop._append_tool_round(base_messages, [original_call], [
            StreamingToolResult(
                tool_name="inspection.manage",
                call_id="call_1",
                output={"ok": True, "task_id": "ins_1"},
                ok=True,
            ),
            StreamingToolResult(
                tool_name="inspection.manage",
                call_id="call_1_poll_1",
                output={"ok": True, "tracking": {"task_id": "ins_1", "status": "running"}},
                ok=True,
            ),
        ])

        tool_messages = [m for m in messages if m.role == "tool"]
        assert [m.tool_call_id for m in tool_messages] == ["call_1"]
        assert any(
            m.role == "user" and "AUTO TRACKING RESULTS" in (m.content or "")
            for m in messages
        )

    def test_query_loop_tool_definitions_are_cached_and_isolated(self):
        """All tools remain visible, but repeated builds reuse a stable cache."""
        from core.runtime_engine.query_loop import _build_cached_tool_definitions

        registry = {
            "web.manage": {
                "description": "Web search and weather",
                "args_schema": {
                    "required": ["action"],
                    "properties": {
                        "action": {"type": "string", "enum": ["search", "weather"]},
                        "query": {"type": "string"},
                    },
                },
            }
        }

        first = _build_cached_tool_definitions(registry)
        first[0]["function"]["description"] = "mutated by caller"
        second = _build_cached_tool_definitions(registry)

        assert len(second) == 1
        assert second[0]["function"]["name"] == "web__manage"
        assert second[0]["function"]["description"] != "mutated by caller"

    def test_query_loop_compacts_tool_outputs_without_losing_control_fields(self, config):
        """Large tool payloads should not snowball into the next LLM turn."""
        from agent.llm.schemas import LLMMessage, LLMToolCall
        from core.runtime_engine.query_loop import QueryLoop, StreamingToolResult

        class RuntimeStub:
            def has_tool(self, name):
                return name == "inspection.manage"

        loop = QueryLoop(
            config=config,
            tool_registry={"inspection.manage": {"description": "Inspection"}},
            tool_runtime=RuntimeStub(),
        )
        messages = loop._append_tool_round(
            [
                LLMMessage(role="system", content="system"),
                LLMMessage(role="user", content="run inspection"),
            ],
            [LLMToolCall(id="call_big", name="inspection.manage", arguments={"action": "get"})],
            [
                StreamingToolResult(
                    tool_name="inspection.manage",
                    call_id="call_big",
                    output={
                        "ok": True,
                        "summary": "巡检完成",
                        "task_id": "ins_123",
                        "report_url": "/artifacts/report.html",
                        "stdout": "x" * 20_000,
                        "rows": [{"name": f"dev-{i}", "status": "ok"} for i in range(50)],
                    },
                    ok=True,
                )
            ],
        )

        tool_msg = next(m for m in messages if m.role == "tool")
        assert len(tool_msg.content or "") < 4200
        assert "巡检完成" in (tool_msg.content or "")
        assert "ins_123" in (tool_msg.content or "")
        assert "/artifacts/report.html" in (tool_msg.content or "")
        assert "_omitted_items" in (tool_msg.content or "")

    @pytest.mark.asyncio
    async def test_full_pipeline_simple_tools(self, config):
        """End-to-end test with mock LLM and mock tools."""
        from core.runtime_engine.engine import SSOTRuntimeEngine

        config.enable_finalizer = False

        # Mock LLM that plans two parallel tools
        plan_json = json.dumps({
            "nodes": [
                {"id": "fetch_status", "tool": "exec.run",
                 "args": {"command": "systemctl status nginx"}, "deps": []},
                {"id": "check_logs", "tool": "workspace.file",
                 "args": {"action": "read", "path": "/var/log/nginx.log"}, "deps": []},
            ]
        })

        def mock_llm(**kwargs):
            return plan_json

        tool_registry = {
            "exec.run": {"description": "Run shell", "args_schema": {
                "required": ["command"], "properties": {"command": {"type": "string"}},
            }},
            "workspace.file": {"description": "File ops", "args_schema": {
                "required": ["action", "path"],
                "properties": {"action": {"type": "string"}, "path": {"type": "string"}},
            }},
        }

        engine = SSOTRuntimeEngine(
            config=config,
            llm_invoke=mock_llm,
            tool_registry=tool_registry,
        )

        async def exec_handler(args):
            await asyncio.sleep(0.01)
            return f"status: online (command: {args.get('command')})"

        async def file_handler(args):
            await asyncio.sleep(0.01)
            return f"log content from {args.get('path')}"

        engine.register_tool("exec.run", exec_handler, description="Run shell")
        engine.register_tool("workspace.file", file_handler, description="File ops")

        result = await engine.run("check nginx status and logs",
                                  extras={"approved_risk": True})

        assert result.success
        assert result.node_success_count == 2
        assert result.node_failure_count == 0
        assert result.planner_latency_ms >= 0
        assert result.execution_latency_ms >= 0
        # 2 LLM calls max (1 planner, no finalizer since disabled)
        assert "fetch_status" in result.node_results
        assert "check_logs" in result.node_results
        assert 0.5 < result.total_latency_ms < 100  # should complete in under 100ms with mocks

    @pytest.mark.asyncio
    async def test_full_pipeline_with_failure_isolation(self, config):
        """One tool fails, the other succeeds — neither blocks the DAG."""
        from core.runtime_engine.engine import SSOTRuntimeEngine

        config.enable_finalizer = False

        plan_json = json.dumps({
            "nodes": [
                {"id": "good", "tool": "web.manage",
                 "args": {"action": "search", "query": "uptime"}, "deps": []},
                {"id": "bad", "tool": "knowledge.manage",
                 "args": {"action": "search", "query": "old_data"}, "deps": []},
            ]
        })

        def mock_llm(**kwargs):
            return plan_json

        tool_registry = {
            "web.manage": {"description": "Web", "args_schema": {
                "required": ["action"], "properties": {"action": {"type": "string"}, "query": {"type": "string"}},
            }},
            "knowledge.manage": {"description": "Knowledge", "args_schema": {
                "required": ["action"], "properties": {"action": {"type": "string"}, "query": {"type": "string"}},
            }},
        }

        engine = SSOTRuntimeEngine(
            config=config,
            llm_invoke=mock_llm,
            tool_registry=tool_registry,
        )

        async def web_handler(args):
            await asyncio.sleep(0.01)
            return f"search results for {args.get('query')}"

        async def bad_handler(args):
            raise RuntimeError("database connection refused")

        engine.register_tool("web.manage", web_handler)
        engine.register_tool("knowledge.manage", bad_handler)

        result = await engine.run("search for uptime and old data")

        # Bank-grade: failure isolation — pipeline succeeds, node failures isolated
        assert result.success
        assert result.node_success_count == 1
        assert result.node_failure_count == 1
        assert result.node_results["good"].success
        assert not result.node_results["bad"].success
        assert "connection refused" in result.node_results["bad"].error

    @pytest.mark.asyncio
    async def test_max_two_llm_calls(self, config):
        """Verify max 2 LLM calls per request (1 planner + 1 finalizer)."""
        from core.runtime_engine.engine import SSOTRuntimeEngine

        llm_call_count = [0]

        plan_json = json.dumps({
            "nodes": [
                {"id": "step1", "tool": "exec.run",
                 "args": {"command": "echo hello"}, "deps": []},
            ]
        })

        def counting_llm(**kwargs):
            llm_call_count[0] += 1
            return plan_json

        tool_registry = {
            "exec.run": {"description": "", "args_schema": {
                "required": ["command"], "properties": {"command": {"type": "string"}},
            }},
        }

        engine = SSOTRuntimeEngine(
            config=config,
            llm_invoke=counting_llm,
            tool_registry=tool_registry,
        )

        async def handler(args):
            return "ok"

        engine.register_tool("exec.run", handler)

        await engine.run("test", extras={"approved_risk": True})

        # 1 planner + 1 finalizer = 2 (since finalizer is enabled by default)
        assert llm_call_count[0] == 2

    @pytest.mark.asyncio
    async def test_runtime_polls_long_task_tracking_before_finalizer(self, config):
        """A long-task tracking payload should trigger bounded get polls."""
        from core.runtime_engine.engine import SSOTRuntimeEngine

        config.enable_finalizer = False
        config.tracking_max_polls = 3
        config.tracking_poll_interval_cap_seconds = 0

        plan_json = json.dumps({
            "nodes": [
                {
                    "id": "n0",
                    "tool": "inspection.manage",
                    "args": {"action": "run", "scope": {"search": "ASBR-PE1"}},
                    "deps": [],
                },
            ],
        })

        def mock_llm(**kwargs):
            return plan_json

        tool_registry = {
            "inspection.manage": {
                "description": "Inspection",
                "args_schema": {
                    "required": ["action"],
                    "properties": {
                        "action": {"type": "string"},
                        "task_id": {"type": "string"},
                    },
                },
            },
        }
        engine = SSOTRuntimeEngine(
            config=config,
            llm_invoke=mock_llm,
            tool_registry=tool_registry,
        )
        polls = {"count": 0}

        async def inspection_handler(args):
            if args.get("action") == "run":
                return {
                    "ok": True,
                    "task_id": "ins_test",
                    "tracking": {
                        "kind": "long_task",
                        "domain": "inspection",
                        "task_id": "ins_test",
                        "status": "running",
                        "done": False,
                        "next_poll_seconds": 0,
            "suggested_next_action": "poll_get",
                        "progress": {"done_devices": 0, "total_devices": 1, "percent": 0},
                        "summary": {"task_id": "ins_test", "status": "running"},
                    },
                }
            assert args.get("action") == "get"
            polls["count"] += 1
            done = polls["count"] >= 2
            status = "succeeded" if done else "running"
            return {
                "ok": True,
                "task": {"task_id": "ins_test", "status": status},
                "tracking": {
                    "kind": "long_task",
                    "domain": "inspection",
                    "task_id": "ins_test",
                    "status": status,
                    "done": done,
                    "terminal": done,
                    "next_poll_seconds": 0,
                    "suggested_next_action": "analyze_artifacts" if done else "poll_get",
                    "progress": {"done_devices": 1 if done else 0, "total_devices": 1, "percent": 100 if done else 0},
                    "summary": {"task_id": "ins_test", "status": status, "succeeded_devices": 1 if done else 0},
                },
            }

        engine.register_tool("inspection.manage", inspection_handler)

        result = await engine.run(
            "请发起巡检并跟踪结果",
            extras={"approved_risk": True},
        )

        assert result.success
        assert polls["count"] == 2
        assert "n0_track_1" in result.node_results
        assert "n0_track_2" in result.node_results
        assert result.metadata["tracking_summary"]["status"] == "succeeded"
        assert result.metadata["tracking_summary"]["done"] is True

    @pytest.mark.asyncio
    async def test_dag_validation_rejects_bad_plan(self, config):
        """A plan with non-existent tool should be rejected at validation."""
        from core.runtime_engine.engine import SSOTRuntimeEngine

        plan_json = json.dumps({
            "nodes": [
                {"id": "invalid", "tool": "no.such.tool", "args": {}, "deps": []},
            ]
        })

        def mock_llm(**kwargs):
            return plan_json

        engine = SSOTRuntimeEngine(
            config=config,
            llm_invoke=mock_llm,
            tool_registry={},  # empty registry
        )

        result = await engine.run("do something impossible")
        assert not result.success
        assert len(result.errors) > 0
        assert len(result.metadata["structured_errors"]) > 0


# ============================================================================
# Latency Model Tests
# ============================================================================

class TestLatencyModel:

    def test_latency_formula(self, config):
        """TOTAL LATENCY = planner + max(layer times) + merge + finalizer"""
        from core.runtime_engine.engine import SSOTRuntimeEngine

        # Quick execution with async sleep tools
        plan_json = json.dumps({
            "nodes": [
                {"id": "t1", "tool": "exec.run", "args": {"delay": 0.02}, "deps": []},
                {"id": "t2", "tool": "exec.run", "args": {"delay": 0.02}, "deps": []},
                {"id": "t3", "tool": "exec.run", "args": {"delay": 0.02}, "deps": ["t1", "t2"]},
            ]
        })

        def mock_llm(**kwargs):
            return plan_json

        registry = {
            "exec.run": {"description": "", "args_schema": {
                "required": ["delay"], "properties": {"delay": {"type": "number"}},
            }},
        }

        engine = SSOTRuntimeEngine(
            config=SSOTRuntimeConfig(enable_finalizer=False),
            llm_invoke=mock_llm,
            tool_registry=registry,
        )

        async def delay_handler(args):
            await asyncio.sleep(args.get("delay", 0.01))
            return f"done"

        engine.register_tool("exec.run", delay_handler)

        result = asyncio.run(engine.run("test"))

        # Verify latency components exist
        assert result.planner_latency_ms >= 0
        assert result.execution_latency_ms >= 0
        assert result.merge_latency_ms >= 0
        assert result.max_layer_latency_ms >= 0

        # max_layer_latency should be ~0.02s (the longest layer)
        # execution_latency ≈ 0.04s (two layers: 0.02 + 0.02)
        assert result.max_layer_latency_ms < 200  # < 200ms (with overhead)
        assert result.execution_latency_ms < 400   # < 400ms (two layers + overhead)

    def test_finalizer_budget_not_consumed_by_slow_tools(self, config):
        """Slow tools must not skip final synthesis by consuming finalizer timeout."""
        from core.runtime_engine.budget_controller import BudgetController

        cfg = SSOTRuntimeConfig(finalizer_timeout_ms=1000, max_total_seconds=60)
        budget = BudgetController(cfg)
        time.sleep(1.05)

        status = budget.check_finalizer()

        assert status.ok
        assert status.exceeded == ""


# ============================================================================
# Edge Cases
# ============================================================================

class TestEdgeCases:

    def test_stateless_context_no_mutation(self, config):
        """Context should not accumulate state between executions."""
        from core.runtime_engine.models import StatelessContext
        ctx = StatelessContext(
            workspace_id="ws", session_id="s1", request_id="r1",
            user_input="first",
        )
        # Verify it's a clean dataclass (no hidden methods)
        assert ctx.user_input == "first"
        ctx2 = StatelessContext(
            workspace_id="ws", session_id="s1", request_id="r2",
            user_input="second",
        )
        assert ctx.user_input == "first"
        assert ctx2.user_input == "second"

    def test_cycle_detection_in_compiler(self, config):
        """Graph compiler should handle cycles (A→B→A)."""
        compiler = GraphCompiler(config)
        nodes = [
            PlanNode(id="A", tool="exec.run", args={}, deps=["B"]),
            PlanNode(id="B", tool="exec.run", args={}, deps=["A"]),
        ]
        # Should not raise — cycle-breaking logic should handle it
        dag = compiler.compile(nodes)
        assert dag.total_nodes == 2
        # At least one node should have deps cleared
        assert any(not n.deps for n in dag.nodes)

    def test_planner_system_prompt_conforms_to_spec(self):
        """Verify planner prompt matches the current function-calling contract."""
        assert "Invoke ALL independent tools in a single response" in PLANNER_SYSTEM_PROMPT
        assert "parallel execution" in PLANNER_SYSTEM_PROMPT
        assert "invoke NO tools" in PLANNER_SYSTEM_PROMPT
        assert "Preserve user intent in tool arguments" in PLANNER_SYSTEM_PROMPT
        assert "Never invent aliases" in PLANNER_SYSTEM_PROMPT
        assert "fewer tools = faster execution" in PLANNER_SYSTEM_PROMPT
        assert 'action="get"' in PLANNER_SYSTEM_PROMPT
        assert "run_and_wait" not in PLANNER_SYSTEM_PROMPT

    def test_finalizer_strips_provider_reasoning(self):
        """Provider reasoning tags must never be persisted as final response."""
        from core.runtime_engine.finalizer import _strip_reasoning_output

        assert _strip_reasoning_output("<think>hidden</think>\n最终结论") == "最终结论"
        assert _strip_reasoning_output("<think>hidden without close") == ""
