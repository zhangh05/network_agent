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
        assert result.metadata["dag_nodes"] == 0

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
        """Verify planner prompt forbids reasoning and multi-step thinking."""
        assert "ONLY valid JSON" in PLANNER_SYSTEM_PROMPT
        assert "no preamble" in PLANNER_SYSTEM_PROMPT
        assert "no explanation" in PLANNER_SYSTEM_PROMPT
        assert "WILL execute in parallel" in PLANNER_SYSTEM_PROMPT
        # Must explicitly forbid reasoning
        assert "NOT include reasoning" in PLANNER_SYSTEM_PROMPT
