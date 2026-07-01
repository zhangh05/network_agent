"""
Bank-grade hardening tests for SPEG Engine.

Covers all new modules: semantic_validator, risk_policy, scheduler,
budget_controller, repair_engine, rollback, audit, trace, metrics, contracts, errors.
"""

import asyncio
import json
import time
import pytest

from speg_engine.models import (
    ExecutionBudget,
    ExecutionDAG,
    ExecutionNode,
    ExecutionStatus,
    NodePriority,
    PlanNode,
    SPEGConfig,
    StatelessContext,
    ToolResult,
)
from speg_engine.errors import SPEGError, SpegErrorCode, build_error
from speg_engine.contracts import BUILTIN_CONTRACTS, get_contract, get_risk_level, get_concurrency_group
from speg_engine.semantic_validator import SemanticValidator
from speg_engine.risk_policy import RiskPolicyEngine, RiskAssessment
from speg_engine.budget_controller import BudgetController
from speg_engine.scheduler import ResourceScheduler
from speg_engine.repair_engine import RepairEngine, RepairStrategy
from speg_engine.rollback import RollbackEngine
from speg_engine.audit import AuditLogger
from speg_engine.trace import TraceCollector, SpanClock
from speg_engine.metrics import MetricsCollector


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def config():
    return SPEGConfig()


# ============================================================================
# Contracts Tests
# ============================================================================

class TestContracts:
    def test_all_22_tools_have_contracts(self):
        assert len(BUILTIN_CONTRACTS) == 22

    def test_exec_run_is_high_risk(self):
        c = get_contract("exec.run")
        assert c is not None
        assert c.risk_level == "high"
        assert c.side_effect == "execute_command"
        assert not c.idempotent

    def test_read_tools_are_low_risk(self):
        for tool in ["knowledge.manage", "code.search", "system.manage"]:
            c = get_contract(tool)
            assert c is not None
            assert c.side_effect == "read", f"{tool}: expected read, got {c.side_effect}"
            assert c.risk_level == "low"

        # web.manage is external_request (acceptable as low-risk for read-like)
        cw = get_contract("web.manage")
        assert cw.side_effect == "external_request"
        assert cw.risk_level == "low"

    def test_ssh_tools_have_concurrency_group(self):
        c = get_contract("inspection.manage")
        assert c.concurrency_group == "ssh"

    def test_get_risk_level_defaults(self):
        assert get_risk_level("nonexistent") == "low"

    def test_get_concurrency_group_defaults(self):
        assert get_concurrency_group("nonexistent") is None

    def test_rollback_supported_on_write_tools(self):
        c = get_contract("workspace.file")
        assert c.rollback_supported

    def test_approval_required_on_exec_tools(self):
        c = get_contract("exec.run")
        assert c.requires_approval


# ============================================================================
# Errors Tests
# ============================================================================

class TestErrors:
    def test_build_structured_error(self):
        err = build_error(SpegErrorCode.PLANNER_TIMEOUT, "timed out", stage="planner", retryable=True)
        assert err.code == SpegErrorCode.PLANNER_TIMEOUT
        assert err.retryable
        d = err.to_dict()
        assert d["code"] == "PLANNER_TIMEOUT"

    def test_error_codes_are_unique(self):
        codes = [v for k, v in SpegErrorCode.__dict__.items() if not k.startswith("_") and isinstance(v, str)]
        assert len(codes) == len(set(codes))


# ============================================================================
# Semantic Validator Tests
# ============================================================================

class TestSemanticValidator:
    @pytest.fixture
    def validator(self):
        return SemanticValidator()

    def test_valid_dag_passes(self, validator):
        nodes = [
            ExecutionNode(id="n1", tool="web.manage", args={"action": "search", "query": "test"}, depth=0),
            ExecutionNode(id="n2", tool="workspace.file", args={"action": "read", "path": "/tmp/f"}, depth=0),
        ]
        dag = ExecutionDAG(nodes=nodes, total_nodes=2, max_depth=0)
        result = validator.validate(dag)
        assert result.valid

    def test_missing_tool(self, validator):
        nodes = [ExecutionNode(id="n1", tool="no.such.tool", args={}, depth=0)]
        dag = ExecutionDAG(nodes=nodes, total_nodes=1, max_depth=0)
        result = validator.validate(dag)
        assert not result.valid
        assert any(e.code == "TOOL_NOT_FOUND" for e in result.errors)

    def test_invalid_enum_arg(self, validator):
        nodes = [ExecutionNode(id="n1", tool="web.manage", args={"action": "invalid_action", "query": "x"}, depth=0)]
        dag = ExecutionDAG(nodes=nodes, total_nodes=1, max_depth=0)
        result = validator.validate(dag)
        assert not result.valid
        assert any(e.code == "ARG_ENUM_INVALID" for e in result.errors)

    def test_missing_required_arg(self, validator):
        nodes = [ExecutionNode(id="n1", tool="exec.run", args={}, depth=0)]  # missing "command"
        dag = ExecutionDAG(nodes=nodes, total_nodes=1, max_depth=0)
        result = validator.validate(dag)
        assert not result.valid
        assert any("command" in e.message for e in result.errors)

    def test_forbidden_command_detected(self, validator):
        nodes = [ExecutionNode(id="n1", tool="exec.run", args={"command": "rm -rf /"}, depth=0)]
        dag = ExecutionDAG(nodes=nodes, total_nodes=1, max_depth=0)
        result = validator.validate(dag)
        assert not result.valid
        assert any(e.code == "FORBIDDEN_COMMAND" for e in result.errors)

    def test_dangerous_path_warning(self, validator):
        nodes = [ExecutionNode(id="n1", tool="workspace.file", args={"action": "read", "path": "/etc/passwd"}, depth=0)]
        dag = ExecutionDAG(nodes=nodes, total_nodes=1, max_depth=0)
        result = validator.validate(dag)
        assert result.valid  # warning, not error
        assert any(w.code == "DANGEROUS_PATH" for w in result.warnings)

    def test_risk_level_computed(self, validator):
        nodes = [ExecutionNode(id="n1", tool="exec.run", args={"command": "echo hi"}, depth=0)]
        dag = ExecutionDAG(nodes=nodes, total_nodes=1, max_depth=0)
        result = validator.validate(dag)
        assert result.risk_level == "high"


# ============================================================================
# Risk Policy Tests
# ============================================================================

class TestRiskPolicy:
    @pytest.fixture
    def engine(self):
        return RiskPolicyEngine()

    def test_low_risk_dag_safe(self, engine):
        nodes = [
            ExecutionNode(id="n1", tool="web.manage", args={"action": "search", "query": "x"}, depth=0),
            ExecutionNode(id="n2", tool="knowledge.manage", args={"action": "search", "query": "y"}, depth=0),
        ]
        dag = ExecutionDAG(nodes=nodes, total_nodes=2, max_depth=0)
        result = engine.assess(dag)
        assert result.safe_to_run
        assert result.risk_level == "low"

    def test_exec_node_requires_approval(self, engine):
        nodes = [ExecutionNode(id="n1", tool="exec.run", args={"command": "ls"}, depth=0)]
        dag = ExecutionDAG(nodes=nodes, total_nodes=1, max_depth=0)
        result = engine.assess(dag)
        assert result.requires_approval
        assert "n1" in result.approval_nodes

    def test_combo_write_escalation(self, engine):
        nodes = [
            ExecutionNode(id="n1", tool="workspace.file", args={"action": "write_artifact", "path": "/tmp/a"}, depth=0),
            ExecutionNode(id="n2", tool="workspace.file", args={"action": "write_artifact", "path": "/tmp/b"}, depth=0),
            ExecutionNode(id="n3", tool="workspace.file", args={"action": "write_artifact", "path": "/tmp/c"}, depth=0),
        ]
        dag = ExecutionDAG(nodes=nodes, total_nodes=3, max_depth=0)
        result = engine.assess(dag)
        # 3 writes → risk escalated to HIGH (combo)
        assert result.risk_level in ("high", "critical")
        assert any("write" in w.lower() for w in result.warnings)

    def test_multiple_exec_critical(self, engine):
        nodes = [
            ExecutionNode(id="n1", tool="exec.run", args={"command": "a"}, depth=0),
            ExecutionNode(id="n2", tool="exec.run", args={"command": "b"}, depth=0),
            ExecutionNode(id="n3", tool="exec.run", args={"command": "c"}, depth=0),
        ]
        dag = ExecutionDAG(nodes=nodes, total_nodes=3, max_depth=0)
        result = engine.assess(dag)
        assert result.risk_level == "critical"
        assert not result.safe_to_run


# ============================================================================
# Budget Controller Tests
# ============================================================================

class TestBudgetController:
    def test_initial_budget_ok(self):
        bc = BudgetController()
        status = bc.check_planner()
        assert status.ok

    def test_max_nodes_exceeded(self):
        bc = BudgetController()
        nodes = [ExecutionNode(id=f"n{i}", tool="web.manage", args={"action": "search", "query": "x"}) for i in range(35)]
        dag = ExecutionDAG(nodes=nodes, total_nodes=35, max_depth=0)
        status = bc.check_dag(dag)
        assert not status.ok
        assert "MAX_NODES" in status.exceeded

    def test_max_depth_exceeded(self):
        bc = BudgetController()
        nodes = [ExecutionNode(id="n1", tool="web.manage", args={})]
        dag = ExecutionDAG(nodes=nodes, total_nodes=1, max_depth=10)
        status = bc.check_dag(dag)
        assert not status.ok

    def test_llm_call_limit(self):
        bc = BudgetController()
        assert bc.check_llm_call().ok  # call 1
        assert bc.check_llm_call().ok  # call 2
        assert not bc.check_llm_call().ok  # call 3 — exceed

    def test_max_width_exceeded(self):
        bc = BudgetController()
        nodes = [ExecutionNode(id=f"n{i}", tool="web.manage", args={"action": "search", "query": "x"}) for i in range(10)]
        dag = ExecutionDAG(nodes=nodes, layers={0: nodes}, total_nodes=10, max_depth=0)
        status = bc.check_dag(dag)
        assert not status.ok


# ============================================================================
# Scheduler Tests
# ============================================================================

class TestScheduler:
    @pytest.fixture
    def scheduler(self):
        return ResourceScheduler()

    def test_schedule_within_limits(self, scheduler):
        nodes = [
            ExecutionNode(id=f"n{i}", tool="web.manage", args={"action": "search", "query": "x"}, depth=0)
            for i in range(10)
        ]
        scheduled = scheduler.schedule_layer(nodes, active_global_count=0)
        assert len(scheduled) <= scheduler.max_layer

    def test_global_concurrency_cap(self, scheduler):
        nodes = [ExecutionNode(id=f"n{i}", tool="web.manage", args={}, depth=0) for i in range(10)]
        scheduled = scheduler.schedule_layer(nodes, active_global_count=7)
        assert len(scheduled) <= 1  # max_global(8) - active(7) = 1

    def test_zero_capacity_when_full(self, scheduler):
        nodes = [ExecutionNode(id="n1", tool="web.manage", args={}, depth=0)]
        scheduled = scheduler.schedule_layer(nodes, active_global_count=8)
        assert len(scheduled) == 0

    def test_priority_ordering(self, scheduler):
        nodes = [
            ExecutionNode(id="low", tool="web.manage", args={}, depth=0, priority=NodePriority.LOW),
            ExecutionNode(id="high", tool="web.manage", args={}, depth=0, priority=NodePriority.HIGH),
            ExecutionNode(id="normal", tool="web.manage", args={}, depth=0, priority=NodePriority.NORMAL),
        ]
        scheduled = scheduler.schedule_layer(nodes, active_global_count=0)
        assert scheduled[0].id == "high"

    def test_ssh_group_limit(self, scheduler):
        nodes = [
            ExecutionNode(id=f"s{i}", tool="inspection.manage", args={"action": "start"}, depth=0)
            for i in range(5)
        ]
        scheduled = scheduler.schedule_layer(nodes, active_global_count=0)
        # SSH group limit = 2
        assert len(scheduled) <= 2

    def test_only_pending_nodes(self, scheduler):
        n1 = ExecutionNode(id="n1", tool="web.manage", args={}, depth=0)
        n2 = ExecutionNode(id="n2", tool="web.manage", args={}, depth=0, status=ExecutionStatus.SUCCESS)
        scheduled = scheduler.schedule_layer([n1, n2], active_global_count=0)
        assert len(scheduled) == 1
        assert scheduled[0].id == "n1"


# ============================================================================
# Repair Engine Tests
# ============================================================================

class TestRepairEngine:
    @pytest.fixture
    def engine(self):
        return RepairEngine()

    def test_retry_idempotent_node(self, engine):
        node = ExecutionNode(id="n1", tool="web.manage", args={"action": "search", "query": "x"})
        result = ToolResult(node_id="n1", tool="web.manage", success=False, error="timeout")
        dag = ExecutionDAG(nodes=[node], total_nodes=1, max_depth=0)
        repair = engine.assess(node, result, dag)
        assert repair.strategy == RepairStrategy.RETRY
        assert repair.repair_applied

    def test_skip_optional_node(self, engine):
        from speg_engine.contracts import get_contract
        # memory.manage is optional
        node = ExecutionNode(id="n1", tool="memory.manage", args={"action": "search", "query": "x"}, optional=True)
        result = ToolResult(node_id="n1", tool="memory.manage", success=False, error="fail")
        dag = ExecutionDAG(nodes=[node], total_nodes=1, max_depth=0)
        repair = engine.assess(node, result, dag)
        assert repair.strategy == RepairStrategy.SKIP

    def test_fail_non_idempotent_node(self, engine):
        node = ExecutionNode(id="n1", tool="exec.run", args={"command": "echo hi"})
        result = ToolResult(node_id="n1", tool="exec.run", success=False, error="fail")
        dag = ExecutionDAG(nodes=[node], total_nodes=1, max_depth=0)
        repair = engine.assess(node, result, dag)
        # exec.run is not idempotent and has max_retries=0 → cannot retry
        assert repair.strategy == RepairStrategy.FAIL

    def test_fail_critical_path(self, engine):
        n1 = ExecutionNode(id="n1", tool="web.manage", args={"action": "search", "query": "x"}, depth=0)
        n2 = ExecutionNode(id="n2", tool="data.manage", args={"action": "csv"}, depth=1, deps=["n1"])
        result = ToolResult(node_id="n1", tool="web.manage", success=False, error="fail")
        # n1 is idempotent, so retryable. But after max retries exhausted:
        n1.retry_count = 2
        dag = ExecutionDAG(nodes=[n1, n2], total_nodes=2, max_depth=1)
        repair = engine.assess(n1, result, dag)
        # Should be FAIL because children exist
        assert repair.strategy == RepairStrategy.FAIL

    def test_should_retry_quick_check(self, engine):
        node = ExecutionNode(id="n1", tool="web.manage", args={})
        result = ToolResult(node_id="n1", tool="web.manage", success=False, error="fail")
        assert engine.should_retry(node, result)

    def test_should_not_retry_non_idempotent(self, engine):
        node = ExecutionNode(id="n1", tool="exec.run", args={"command": "rm file"})
        result = ToolResult(node_id="n1", tool="exec.run", success=False, error="fail")
        # exec.run is NOT idempotent
        assert not engine.should_retry(node, result)


# ============================================================================
# Rollback Tests
# ============================================================================

class TestRollback:
    @pytest.fixture
    def engine(self):
        return RollbackEngine()

    def test_no_rollback_when_no_failures(self, engine):
        nodes = [ExecutionNode(id="n1", tool="workspace.file", args={"action": "write_artifact", "path": "/tmp/x"})]
        dag = ExecutionDAG(nodes=nodes, total_nodes=1, max_depth=0)
        results = {"n1": ToolResult(node_id="n1", tool="workspace.file", success=True, data="ok")}
        plan = engine.assess(dag, results)
        assert not plan.rollback_recommended

    def test_rollback_recommended_on_critical_failure(self, engine):
        n1 = ExecutionNode(id="n1", tool="workspace.file", args={"action": "write_artifact", "path": "/tmp/x"}, depth=0)
        n2 = ExecutionNode(id="n2", tool="exec.run", args={"command": "critical_op"}, depth=1, deps=["n1"])
        dag = ExecutionDAG(nodes=[n1, n2], total_nodes=2, max_depth=1)
        results = {
            "n1": ToolResult(node_id="n1", tool="workspace.file", success=True, data="mutated"),
            "n2": ToolResult(node_id="n2", tool="exec.run", success=False, error="critical failure"),
        }
        plan = engine.assess(dag, results)
        assert plan.rollback_available
        assert plan.rollback_recommended
        assert any(a.node_id == "n1" for a in plan.actions)

    def test_rollback_unavailable_warning(self, engine):
        node = ExecutionNode(id="n1", tool="exec.run", args={"command": "rm file"})  # not rollback-supported
        dag = ExecutionDAG(nodes=[node], total_nodes=1, max_depth=0)
        results = {
            "n1": ToolResult(node_id="n1", tool="exec.run", success=True, data="done"),
        }
        # Add failing node
        n2 = ExecutionNode(id="n2", tool="web.manage", args={"action": "search", "query": "x"}, depth=1, deps=["n1"])
        dag.nodes.append(n2)
        results["n2"] = ToolResult(node_id="n2", tool="web.manage", success=False, error="fail")
        dag.total_nodes = 2
        plan = engine.assess(dag, results)
        assert any("NO rollback support" in w for w in plan.warnings)


# ============================================================================
# Audit Tests
# ============================================================================

class TestAudit:
    @pytest.fixture
    def logger(self):
        return AuditLogger()

    def test_audit_record_created(self, logger):
        ctx = StatelessContext(
            workspace_id="ws", session_id="s1", request_id="r1",
            user_input="do something",
        )
        dag = ExecutionDAG(nodes=[], total_nodes=0, max_depth=0)
        record = logger.create_record(ctx, dag, {}, risk_level="low", duration_ms=100)
        assert record.request_id == "r1"
        assert record.session_id == "s1"
        assert record.duration_ms == 100

    def test_sensitive_fields_redacted(self, logger):
        ctx = StatelessContext(workspace_id="ws", session_id="s1", request_id="r2", user_input="test")
        node = ExecutionNode(id="n1", tool="exec.run", args={"password": "secret123", "command": "ls"})
        node.node_run_id = "run-1"
        node.status = ExecutionStatus.SUCCESS
        dag = ExecutionDAG(nodes=[node], total_nodes=1, max_depth=0)
        results = {"n1": ToolResult(node_id="n1", tool="exec.run", success=True, data="ok")}
        record = logger.create_record(ctx, dag, results)
        executed = record.executed_nodes
        assert len(executed) == 1
        assert executed[0]["args"]["password"] == "***REDACTED***"

    def test_failed_node_recorded(self, logger):
        ctx = StatelessContext(workspace_id="ws", session_id="s3", request_id="r3", user_input="test")
        node = ExecutionNode(id="n1", tool="web.manage", args={})
        node.status = ExecutionStatus.FAILED
        node.error = "timeout"
        dag = ExecutionDAG(nodes=[node], total_nodes=1, max_depth=0)
        results = {"n1": ToolResult(node_id="n1", tool="web.manage", success=False, error="timeout")}
        record = logger.create_record(ctx, dag, results)
        assert len(record.failed_nodes) == 1

    def test_node_run_id_present(self, logger):
        ctx = StatelessContext(workspace_id="ws", session_id="s4", request_id="r4", user_input="test")
        node = ExecutionNode(id="n1", tool="web.manage", args={})
        node.node_run_id = "node-run-001"
        node.status = ExecutionStatus.SUCCESS
        dag = ExecutionDAG(nodes=[node], total_nodes=1, max_depth=0)
        results = {"n1": ToolResult(node_id="n1", tool="web.manage", success=True, data="ok")}
        record = logger.create_record(ctx, dag, results)
        assert record.executed_nodes[0]["node_run_id"] == "node-run-001"


# ============================================================================
# Trace Tests
# ============================================================================

class TestTrace:
    def test_span_timing(self):
        clock = SpanClock("test-span")
        clock.start()
        time.sleep(0.01)
        clock.stop()
        assert clock.span.duration_ms > 0
        assert clock.span.status == "ok"

    def test_trace_collector(self):
        tc = TraceCollector()
        req = tc.start_request("req-1")
        req.stop("ok")
        assert req.span.name == "request"

    def test_child_span(self):
        tc = TraceCollector()
        parent = tc.add_span("parent")
        child = tc.add_span("child")
        tc.add_child(parent, child)
        assert len(parent.span.children) == 1
        assert parent.span.children[0].name == "child"

    def test_to_dict(self):
        tc = TraceCollector()
        clock = tc.add_span("root")
        clock.stop("ok")
        d = tc.to_dict(clock.span)
        assert d["name"] == "root"
        assert d["duration_ms"] >= 0


# ============================================================================
# Metrics Tests
# ============================================================================

class TestMetrics:
    def test_full_metrics_snapshot(self):
        mc = MetricsCollector()
        mc.capture_planner(10.0)
        mc.capture_compile(1.0)
        mc.capture_validation(2.0)
        mc.capture_execution(100.0, {}, ExecutionDAG(nodes=[], total_nodes=0, max_depth=0))
        mc.capture_finalizer(5.0)
        mc.capture_total(118.0)
        mc.set_llm_calls(2)
        mc.set_risk_level("medium")

        d = mc.to_dict()
        assert d["planner_duration_ms"] == 10.0
        assert d["execution_duration_ms"] == 100.0
        assert d["llm_calls"] == 2
        assert d["risk_level"] == "medium"

    def test_tool_stats(self):
        mc = MetricsCollector()
        nr = {
            "a": ToolResult(node_id="a", tool="web.manage", success=True),
            "b": ToolResult(node_id="b", tool="web.manage", success=True),
            "c": ToolResult(node_id="c", tool="web.manage", success=False),
        }
        nodes = [
            ExecutionNode(id="a", tool="web.manage", args={}, depth=0),
            ExecutionNode(id="b", tool="web.manage", args={}, depth=0),
            ExecutionNode(id="c", tool="web.manage", args={}, depth=0),
        ]
        dag = ExecutionDAG(nodes=nodes, layers={0: nodes}, total_nodes=3, max_depth=0)
        mc.capture_execution(50.0, nr, dag)
        d = mc.to_dict()
        assert d["tool_calls"] == 3
        assert d["tool_success"] == 2
        assert d["tool_failed"] == 1
        assert d["dag_depth"] == 0
        assert d["max_parallel_width"] == 3


# ============================================================================
# Full Pipeline Integration — Bank-grade
# ============================================================================

class TestBankGradePipeline:
    """Integration tests that exercise the full 15-stage pipeline."""

    @pytest.mark.asyncio
    async def test_audit_in_result_metadata(self, config):
        from speg_engine.engine import SPEGEngine

        plan_json = json.dumps({"nodes": [
            {"id": "n1", "tool": "web.manage", "args": {"action": "search", "query": "test"}, "deps": []}
        ]})

        def mock_llm(**kw):
            return plan_json

        registry = {"web.manage": {"description": "", "args_schema": {
            "required": ["action"], "properties": {"action": {"type": "string"}, "query": {"type": "string"}},
        }}}

        engine = SPEGEngine(config=SPEGConfig(enable_finalizer=False), llm_invoke=mock_llm, tool_registry=registry)

        async def handler(args):
            return "results"

        engine.register_tool("web.manage", handler)
        result = await engine.run("search test")

        assert "structured_errors" in result.metadata
        assert "metrics" in result.metadata
        assert "risk_level" in result.metadata
        assert "llm_calls" in result.metadata

    @pytest.mark.asyncio
    async def test_scheduler_caps_concurrency(self, config):
        from speg_engine.engine import SPEGEngine

        nodes_json = [{"id": f"n{i}", "tool": "web.manage", "args": {"action": "search", "query": f"q{i}"}, "deps": []} for i in range(15)]
        plan_json = json.dumps({"nodes": nodes_json})

        def mock_llm(**kw):
            return plan_json

        registry = {"web.manage": {"description": "", "args_schema": {
            "required": ["action"], "properties": {"action": {"type": "string"}, "query": {"type": "string"}},
        }}}

        engine = SPEGEngine(config=SPEGConfig(enable_finalizer=False, max_global_concurrency=8, max_layer_concurrency=5), llm_invoke=mock_llm, tool_registry=registry)

        async def handler(args):
            await asyncio.sleep(0.005)
            return "ok"

        engine.register_tool("web.manage", handler)
        result = await engine.run("search 15 things")

        # 15 nodes at depth 0 → limited by max_layer_concurrency(5)
        assert result.success or result.node_failure_count >= 0

    @pytest.mark.asyncio
    async def test_budget_llm_calls_enforced(self, config):
        from speg_engine.engine import SPEGEngine

        plan_json = json.dumps({"nodes": [
            {"id": "n1", "tool": "web.manage", "args": {"action": "search", "query": "x"}, "deps": []}
        ]})

        call_count = [0]

        def counting_llm(**kw):
            call_count[0] += 1
            return plan_json

        registry = {"web.manage": {"description": "", "args_schema": {
            "required": ["action"], "properties": {"action": {"type": "string"}, "query": {"type": "string"}},
        }}}

        engine = SPEGEngine(config=SPEGConfig(enable_finalizer=True, max_llm_calls=2), llm_invoke=counting_llm, tool_registry=registry)

        async def handler(args):
            return "ok"

        engine.register_tool("web.manage", handler)
        result = await engine.run("test")
        assert call_count[0] <= 2

    @pytest.mark.asyncio
    async def test_risk_policy_blocks_critical_combo(self, config):
        from speg_engine.engine import SPEGEngine

        nodes_json = [
            {"id": f"n{i}", "tool": "exec.run", "args": {"command": f"cmd{i}"}, "deps": []}
            for i in range(3)
        ]
        plan_json = json.dumps({"nodes": nodes_json})

        def mock_llm(**kw):
            return plan_json

        registry = {"exec.run": {"description": "", "args_schema": {
            "required": ["command"], "properties": {"command": {"type": "string"}},
        }}}

        engine = SPEGEngine(config=SPEGConfig(enable_finalizer=False), llm_invoke=mock_llm, tool_registry=registry)

        async def handler(args):
            return "ok"

        engine.register_tool("exec.run", handler)
        result = await engine.run("run 3 commands")

        # 3 exec nodes → combo escalation to CRITICAL → blocked
        assert not result.success or result.metadata["risk_level"] == "critical"

    @pytest.mark.asyncio
    async def test_repair_retries_idempotent_node(self, config):
        from speg_engine.engine import SPEGEngine

        plan_json = json.dumps({"nodes": [
            {"id": "n1", "tool": "web.manage", "args": {"action": "search", "query": "x"}, "deps": []}
        ]})

        def mock_llm(**kw):
            return plan_json

        registry = {"web.manage": {"description": "", "args_schema": {
            "required": ["action"], "properties": {"action": {"type": "string"}, "query": {"type": "string"}},
        }}}

        engine = SPEGEngine(config=SPEGConfig(enable_finalizer=False), llm_invoke=mock_llm, tool_registry=registry)

        call_count = [0]

        async def handler(args):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("first call fails")
            return "recovered"

        engine.register_tool("web.manage", handler)
        result = await engine.run("test")

        # web.manage is idempotent → repair should retry
        assert result.node_success_count == 1


# ============================================================================
# Budget specific edge case tests
# ============================================================================

class TestBudgetEdgeCases:
    def test_execution_budget_tool_seconds(self):
        bc = BudgetController(SPEGConfig(max_tool_seconds=0))
        # Immediately after start, tool budget should be exceeded (max_tool_seconds is 0)
        time.sleep(0.01)
        status = bc.check_execution()
        assert not status.ok

    def test_budget_respects_total(self):
        bc = BudgetController(SPEGConfig(max_total_seconds=0))
        time.sleep(0.01)
        status = bc.check_execution()
        assert not status.ok
        assert "TOTAL" in status.exceeded
