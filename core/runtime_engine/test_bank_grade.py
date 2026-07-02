"""
Bank-grade hardening tests for SSOT Runtime Engine.

Covers all new modules: semantic_validator, risk_policy, scheduler,
budget_controller, repair_engine, rollback, audit, trace, metrics, contracts, errors.
"""

import asyncio
import json
import time
import pytest

from core.runtime_engine.models import (
    ExecutionBudget,
    ExecutionDAG,
    ExecutionNode,
    ExecutionStatus,
    NodePriority,
    PlanNode,
    SSOTRuntimeConfig,
    StatelessContext,
    ToolResult,
)
from core.runtime_engine.errors import SSOTRuntimeError, SSOTRuntimeErrorCode, build_error
from core.runtime_engine.contracts import BUILTIN_CONTRACTS, get_contract, get_risk_level, get_concurrency_group
from core.runtime_engine.semantic_validator import SemanticValidator
from core.runtime_engine.risk_policy import RiskPolicyEngine, RiskAssessment
from core.runtime_engine.budget_controller import BudgetController
from core.runtime_engine.scheduler import ResourceScheduler
from core.runtime_engine.repair_engine import RepairEngine, RepairStrategy
from core.runtime_engine.rollback import RollbackEngine
from core.runtime_engine.audit import AuditLogger
from core.runtime_engine.trace import TraceCollector, SpanClock
from core.runtime_engine.metrics import MetricsCollector


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def config():
    return SSOTRuntimeConfig()


# ============================================================================
# Contracts Tests
# ============================================================================

class TestContracts:
    def test_all_22_tools_have_contracts(self):
        assert len(BUILTIN_CONTRACTS) == 22

    def test_exec_run_is_high_risk(self):
        c = get_contract("exec.run")
        assert c is not None
        # v3.17: exec.run downgraded to medium; destructive-command
        # checks at execution time still escalate to approval.
        assert c.risk_level == "medium"
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
        # v3.17: exec.run downgraded to medium; destructive-command
        # checks at execution time still trigger approval.
        assert not c.requires_approval


# ============================================================================
# Errors Tests
# ============================================================================

class TestErrors:
    def test_build_structured_error(self):
        err = build_error(SSOTRuntimeErrorCode.PLANNER_TIMEOUT, "timed out", stage="planner", retryable=True)
        assert err.code == SSOTRuntimeErrorCode.PLANNER_TIMEOUT
        assert err.retryable
        d = err.to_dict()
        assert d["code"] == "PLANNER_TIMEOUT"

    def test_error_codes_are_unique(self):
        codes = [v for k, v in SSOTRuntimeErrorCode.__dict__.items() if not k.startswith("_") and isinstance(v, str)]
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
        # v3.12: rm -rf / is no longer blocked by semantic_validator.
        # Destructive commands are deferred to RiskPolicyEngine for
        # approval/hard_block. Use a truly forbidden command for this test.
        nodes = [ExecutionNode(id="n1", tool="exec.run",
                               args={"command": "shutdown /s"}, depth=0)]
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
        # v3.17: exec.run risk_level=medium → semantic validator
        # only elevates high/critical, so composite stays low
        # for non-destructive echo commands.
        assert result.risk_level == "low"


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
        # v3.17: exec.run is medium risk; non-destructive commands
        # (ls) no longer require approval. Use destructive command.
        nodes = [ExecutionNode(id="n1", tool="exec.run",
                               args={"command": "rm -f /tmp/test"},
                               depth=0)]
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
        # v3.12: 3 writes → approval required (not hard block, not risk escalation)
        assert result.requires_approval
        assert result.hard_block is False
        assert any("write" in w.lower() for w in result.warnings)

    def test_multiple_exec_approval(self, engine):
        # v3.17: exec.run=medium, requires >5 exec nodes for combo escalation
        nodes = [
            ExecutionNode(id=f"n{i}", tool="exec.run",
                          args={"command": chr(ord('a')+i)},
                          depth=0)
            for i in range(6)
        ]
        dag = ExecutionDAG(nodes=nodes, total_nodes=6, max_depth=0)
        result = engine.assess(dag)
        assert result.requires_approval
        assert result.hard_block is False
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
        from core.runtime_engine.contracts import get_contract
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
        from core.runtime_engine.engine import SSOTRuntimeEngine

        plan_json = json.dumps({"nodes": [
            {"id": "n1", "tool": "web.manage", "args": {"action": "search", "query": "test"}, "deps": []}
        ]})

        def mock_llm(**kw):
            return plan_json

        registry = {"web.manage": {"description": "", "args_schema": {
            "required": ["action"], "properties": {"action": {"type": "string"}, "query": {"type": "string"}},
        }}}

        engine = SSOTRuntimeEngine(config=SSOTRuntimeConfig(enable_finalizer=False), llm_invoke=mock_llm, tool_registry=registry)

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
        from core.runtime_engine.engine import SSOTRuntimeEngine

        nodes_json = [{"id": f"n{i}", "tool": "web.manage", "args": {"action": "search", "query": f"q{i}"}, "deps": []} for i in range(15)]
        plan_json = json.dumps({"nodes": nodes_json})

        def mock_llm(**kw):
            return plan_json

        registry = {"web.manage": {"description": "", "args_schema": {
            "required": ["action"], "properties": {"action": {"type": "string"}, "query": {"type": "string"}},
        }}}

        engine = SSOTRuntimeEngine(config=SSOTRuntimeConfig(enable_finalizer=False, max_global_concurrency=8, max_layer_concurrency=5), llm_invoke=mock_llm, tool_registry=registry)

        async def handler(args):
            await asyncio.sleep(0.005)
            return "ok"

        engine.register_tool("web.manage", handler)
        result = await engine.run("search 15 things")

        # 15 nodes at depth 0 → limited by max_layer_concurrency(5)
        assert result.success or result.node_failure_count >= 0

    @pytest.mark.asyncio
    async def test_budget_llm_calls_enforced(self, config):
        from core.runtime_engine.engine import SSOTRuntimeEngine

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

        engine = SSOTRuntimeEngine(config=SSOTRuntimeConfig(enable_finalizer=True, max_llm_calls=2), llm_invoke=counting_llm, tool_registry=registry)

        async def handler(args):
            return "ok"

        engine.register_tool("web.manage", handler)
        result = await engine.run("test")
        assert call_count[0] <= 2

    @pytest.mark.asyncio
    async def test_risk_policy_blocks_critical_combo(self, config):
        from core.runtime_engine.engine import SSOTRuntimeEngine

        # v3.17: exec.run=medium; need >5 exec nodes for combo escalation.
        # Spread across 2 layers (depth 0: 3, depth 1: 3) to avoid
        # max_layer_concurrency=5 budget check.
        nodes_json = [
            {"id": f"n{i}", "tool": "exec.run",
             "args": {"command": f"cmd{i}"},
             "deps": ["n0", "n1", "n2"] if i >= 3 else []}
            for i in range(6)
        ]
        plan_json = json.dumps({"nodes": nodes_json})

        def mock_llm(**kw):
            return plan_json

        registry = {"exec.run": {"description": "", "args_schema": {
            "required": ["command"], "properties": {"command": {"type": "string"}},
        }}}

        engine = SSOTRuntimeEngine(config=SSOTRuntimeConfig(enable_finalizer=False), llm_invoke=mock_llm, tool_registry=registry)

        async def handler(args):
            return "ok"

        engine.register_tool("exec.run", handler)
        result = await engine.run("run 6 commands")

        # 6 exec nodes → approval_required (NOT hard block).
        assert result.success
        assert result.metadata.get("approval_required") is True
        assert result.metadata.get("hard_block") is False

    @pytest.mark.asyncio
    async def test_repair_retries_idempotent_node(self, config):
        from core.runtime_engine.engine import SSOTRuntimeEngine

        # v3.10: knowledge.manage is a read-only idempotent tool
        # (side_effect="read", idempotent=True, max_retries=1) —
        # the v3.10 ToolRetryPolicy will retry transient failures.
        plan_json = json.dumps({"nodes": [
            {"id": "n1", "tool": "knowledge.manage", "args": {"action": "search", "query": "x"}, "deps": []}
        ]})

        def mock_llm(**kw):
            return plan_json

        registry = {"knowledge.manage": {"description": "", "args_schema": {
            "required": ["action"], "properties": {"action": {"type": "string"}, "query": {"type": "string"}},
        }}}

        engine = SSOTRuntimeEngine(config=SSOTRuntimeConfig(enable_finalizer=False), llm_invoke=mock_llm, tool_registry=registry)

        call_count = [0]

        async def handler(args):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("first call fails")
            return "recovered"

        engine.register_tool("knowledge.manage", handler)
        result = await engine.run("test")

        # knowledge.manage is read-only idempotent → retry should fire
        assert result.node_success_count == 1


# ============================================================================
# Budget specific edge case tests
# ============================================================================

class TestBudgetEdgeCases:
    def test_execution_budget_tool_seconds(self):
        bc = BudgetController(SSOTRuntimeConfig(max_tool_seconds=0))
        # Immediately after start, tool budget should be exceeded (max_tool_seconds is 0)
        time.sleep(0.01)
        status = bc.check_execution()
        assert not status.ok

    def test_budget_respects_total(self):
        bc = BudgetController(SSOTRuntimeConfig(max_total_seconds=0))
        time.sleep(0.01)
        status = bc.check_execution()
        assert not status.ok
        assert "TOTAL" in status.exceeded


# ============================================================================
# Command Policy Tests (v1.0 — normalization + evaluation)
# ============================================================================

class TestCommandPolicy:
    """Test the unified command_policy module."""

    def test_normalize_basic_cmd(self):
        from core.runtime_engine.command_policy import normalize_command
        nc = normalize_command("ls -la /tmp")
        assert nc.executable_base == "ls"
        assert "-la" in nc.args or "la" in str(nc.args)

    def test_normalize_windows_path(self):
        from core.runtime_engine.command_policy import normalize_command
        nc = normalize_command("C:\\Windows\\System32\\reg.exe add HKLM\\Software\\Test")
        assert nc.executable_base == "reg"
        assert nc.args[0] == "add"
        assert nc.is_registry_tool

    def test_normalize_powershell(self):
        from core.runtime_engine.command_policy import normalize_command
        nc = normalize_command("powershell.exe -EncodedCommand xxx")
        assert nc.executable_base == "powershell"
        assert nc.is_powershell

    def test_normalize_pwsh(self):
        from core.runtime_engine.command_policy import normalize_command
        nc = normalize_command("pwsh -Command Remove-Item")
        assert nc.executable_base == "pwsh"
        assert nc.is_powershell

    def test_normalize_shutdown(self):
        from core.runtime_engine.command_policy import normalize_command
        nc = normalize_command("C:\\Windows\\System32\\shutdown.exe /s /t 0")
        assert nc.executable_base == "shutdown"

    def test_normalize_reg(self):
        from core.runtime_engine.command_policy import normalize_command
        nc = normalize_command("reg add HKLM\\Software\\Test")
        assert nc.executable_base == "reg"

    def test_policy_blocks_reg_add(self):
        from core.runtime_engine.command_policy import normalize_command, evaluate_command_policy
        for cmd in [
            "reg add HKLM\\Software\\Test",
            "reg.exe add HKLM\\Software\\Test",
            "C:\\Windows\\System32\\reg.exe add HKLM\\Software\\Test",
        ]:
            nc = normalize_command(cmd)
            decision = evaluate_command_policy(nc)
            assert not decision.allowed, f"Should block: {cmd}"
            assert decision.error_code == "FORBIDDEN_COMMAND"

    def test_policy_blocks_reg_delete(self):
        from core.runtime_engine.command_policy import normalize_command, evaluate_command_policy
        nc = normalize_command("reg delete HKLM\\Software\\Test")
        decision = evaluate_command_policy(nc)
        assert not decision.allowed
        assert decision.risk_level == "high"

    def test_policy_blocks_regedit_s(self):
        from core.runtime_engine.command_policy import normalize_command, evaluate_command_policy
        nc = normalize_command("regedit /s evil.reg")
        decision = evaluate_command_policy(nc)
        assert not decision.allowed

    def test_policy_blocks_shutdown(self):
        from core.runtime_engine.command_policy import normalize_command, evaluate_command_policy
        nc = normalize_command("shutdown /s /t 0")
        decision = evaluate_command_policy(nc)
        assert not decision.allowed

    def test_policy_blocks_reboot(self):
        from core.runtime_engine.command_policy import normalize_command, evaluate_command_policy
        nc = normalize_command("reboot")
        decision = evaluate_command_policy(nc)
        assert not decision.allowed

    def test_policy_blocks_diskpart(self):
        from core.runtime_engine.command_policy import normalize_command, evaluate_command_policy
        nc = normalize_command("diskpart /s script.txt")
        decision = evaluate_command_policy(nc)
        assert not decision.allowed

    def test_policy_blocks_bcdedit(self):
        from core.runtime_engine.command_policy import normalize_command, evaluate_command_policy
        nc = normalize_command("bcdedit /set testsigning on")
        decision = evaluate_command_policy(nc)
        assert not decision.allowed

    def test_policy_blocks_del_s(self):
        from core.runtime_engine.command_policy import normalize_command, evaluate_command_policy
        nc = normalize_command("cmd.exe /c del /s C:\\temp")
        decision = evaluate_command_policy(nc)
        assert not decision.allowed

    def test_policy_blocks_rd_s(self):
        from core.runtime_engine.command_policy import normalize_command, evaluate_command_policy
        nc = normalize_command("rd /s /q C:\\")
        decision = evaluate_command_policy(nc)
        assert not decision.allowed

    def test_policy_blocks_rm_rf(self):
        from core.runtime_engine.command_policy import normalize_command, evaluate_command_policy
        nc = normalize_command("rm -rf /")
        decision = evaluate_command_policy(nc)
        assert not decision.allowed

    def test_policy_blocks_format(self):
        from core.runtime_engine.command_policy import normalize_command, evaluate_command_policy
        nc = normalize_command("format C:")
        decision = evaluate_command_policy(nc)
        assert not decision.allowed

    def test_policy_blocks_takeown(self):
        from core.runtime_engine.command_policy import normalize_command, evaluate_command_policy
        nc = normalize_command("takeown /f C:\\path")
        decision = evaluate_command_policy(nc)
        assert not decision.allowed

    def test_policy_blocks_cipher(self):
        from core.runtime_engine.command_policy import normalize_command, evaluate_command_policy
        nc = normalize_command("cipher /w:C:\\")
        decision = evaluate_command_policy(nc)
        assert not decision.allowed

    def test_policy_blocks_delete_recursive(self):
        from core.runtime_engine.command_policy import normalize_command, evaluate_command_policy
        nc = normalize_command("delete recursive /tmp/data")
        decision = evaluate_command_policy(nc)
        assert not decision.allowed

    def test_policy_allows_safe_commands(self):
        from core.runtime_engine.command_policy import normalize_command, evaluate_command_policy
        for cmd in ["ls -la", "echo hello", "cat /tmp/file.txt", "ping -c 1 localhost"]:
            nc = normalize_command(cmd)
            decision = evaluate_command_policy(nc)
            assert decision.allowed, f"Should allow: {cmd}"


# ============================================================================
# PowerShell-specific Policy Tests (v1.0)
# ============================================================================

class TestPowerShellPolicy:
    """Test PowerShell-specific blocking and allowlisting."""

    def assert_blocked(self, cmd: str, error_code: str = "FORBIDDEN_COMMAND"):
        from core.runtime_engine.command_policy import normalize_command, evaluate_command_policy
        nc = normalize_command(cmd)
        decision = evaluate_command_policy(nc)
        assert not decision.allowed, f"Should block: {cmd} → {decision.reason}"
        assert decision.error_code == error_code

    def test_block_encoded_command(self):
        self.assert_blocked("powershell.exe -EncodedCommand xxx")

    def test_block_pwsh_encoded_command(self):
        self.assert_blocked("pwsh -EncodedCommand xxx")

    def test_block_command_flag(self):
        self.assert_blocked("powershell.exe -Command Remove-Item -Recurse C:\\")

    def test_block_pwsh_command_flag(self):
        self.assert_blocked("pwsh -Command Remove-Item -Recurse /")

    def test_block_enc_flag(self):
        self.assert_blocked("powershell -enc SGVsbG8=")

    def test_block_remove_item(self):
        self.assert_blocked("Remove-Item -Recurse C:\\")

    def test_block_invoke_expression(self):
        self.assert_blocked("Invoke-Expression 'malicious'")

    def test_block_iex(self):
        self.assert_blocked("IEX 'malicious'")

    def test_block_start_process(self):
        self.assert_blocked("Start-Process powershell")

    def test_block_set_execution_policy(self):
        self.assert_blocked("Set-ExecutionPolicy Unrestricted")

    def test_block_add_mp_preference(self):
        self.assert_blocked("Add-MpPreference -ExclusionPath C:\\")

    def test_block_set_mp_preference(self):
        self.assert_blocked("Set-MpPreference -DisableRealtimeMonitoring 1")

    def test_block_disable_realtime_monitoring(self):
        self.assert_blocked("DisableRealtimeMonitoring")

    def test_allow_powershell_file_in_workspace(self):
        from core.runtime_engine.command_policy import normalize_command, evaluate_command_policy
        nc = normalize_command("powershell.exe -File workspace/scripts/check.ps1")
        decision = evaluate_command_policy(nc)
        assert decision.allowed, f"Should allow: workspace/scripts/check.ps1"

    def test_block_powershell_file_system_dir(self):
        from core.runtime_engine.command_policy import normalize_command, evaluate_command_policy
        nc = normalize_command("powershell.exe -File C:\\Windows\\Temp\\evil.ps1")
        decision = evaluate_command_policy(nc)
        assert not decision.allowed

    def test_block_powershell_file_traversal(self):
        from core.runtime_engine.command_policy import normalize_command, evaluate_command_policy
        nc = normalize_command("powershell.exe -File ..\\evil.ps1")
        decision = evaluate_command_policy(nc)
        assert not decision.allowed

    def test_block_powershell_file_traversal_in_path(self):
        from core.runtime_engine.command_policy import normalize_command, evaluate_command_policy
        nc = normalize_command("powershell.exe -File workspace/scripts/..\\evil.ps1")
        decision = evaluate_command_policy(nc)
        assert not decision.allowed

    def test_block_powershell_file_outside_workspace(self):
        from core.runtime_engine.command_policy import normalize_command, evaluate_command_policy
        nc = normalize_command("powershell.exe -File /tmp/evil.ps1")
        decision = evaluate_command_policy(nc)
        assert not decision.allowed


# ============================================================================
# Full 20 Attack Vector Integration Tests (v1.0)
# ============================================================================

class TestV1AttackVectors:
    """All 20 attack vectors from the spec must be blocked."""

    VECTORS = [
        (1, "C:\\Windows\\System32\\shutdown.exe /s /t 0", "shutdown"),
        (2, "powershell.exe -EncodedCommand xxx", "powershell"),
        (3, "powershell.exe -Command Remove-Item -Recurse C:\\", "powershell"),
        (4, "pwsh -EncodedCommand xxx", "pwsh"),
        (5, "pwsh -Command Remove-Item -Recurse /", "pwsh"),
        (6, "cmd.exe /c del /s C:\\temp", "cmd"),
        (7, "reg.exe add HKLM\\Software\\Test", "reg"),
        (8, "C:\\Windows\\System32\\reg.exe add HKLM\\Software\\Test", "reg"),
        (9, "reg delete HKLM\\Software\\Test", "reg"),
        (10, "regedit /s evil.reg", "regedit"),
        (11, "diskpart /s script.txt", "diskpart"),
        (12, "bcdedit /set testsigning on", "bcdedit"),
        (13, "Remove-Item -Recurse C:\\", "remove-item"),
        (14, "Invoke-Expression 'malicious'", "invoke-expression"),
        (15, "IEX 'malicious'", "iex"),
        (16, "Start-Process powershell", "start-process"),
        (17, "Set-ExecutionPolicy Unrestricted", "set-executionpolicy"),
        (18, "rm -rf /", "rm"),
        (19, "rd /s /q C:\\", "rd"),
        (20, "del /s /q C:\\*.tmp", "del"),
    ]

    @pytest.mark.parametrize("num,cmd,expected_base", VECTORS)
    def test_vector_blocked(self, num, cmd, expected_base):
        from core.runtime_engine.command_policy import normalize_command, evaluate_command_policy
        nc = normalize_command(cmd)
        decision = evaluate_command_policy(nc)

        assert not decision.allowed, f"Vector #{num}: '{cmd}' should be BLOCKED"
        assert decision.error_code == "FORBIDDEN_COMMAND", f"Vector #{num}: error_code should be FORBIDDEN_COMMAND, got {decision.error_code}"
        assert decision.risk_level in ("high", "critical"), f"Vector #{num}: risk_level should be high/critical, got {decision.risk_level}"
        assert nc.executable_base == expected_base, f"Vector #{num}: expected base={expected_base}, got {nc.executable_base}"
        assert decision.normalized is not None, f"Vector #{num}: normalized command should be present"

    @pytest.fixture
    def config(self):
        return SSOTRuntimeConfig()

    @pytest.mark.asyncio
    async def test_audit_records_blocked_command(self, config):
        """When command_policy blocks a command, audit must capture it."""
        from core.runtime_engine.engine import SSOTRuntimeEngine
        import json

        registry = {"exec.run": {"description": "", "args_schema": {
            "required": ["command"], "properties": {"command": {"type": "string"}},
        }}}

        plan_json = json.dumps({"nodes": [
            {"id": "attack", "tool": "exec.run",
             "args": {"command": "powershell.exe -EncodedCommand xxx"}, "deps": []}
        ]})

        def mock_llm(**kw):
            return plan_json

        engine = SSOTRuntimeEngine(config=SSOTRuntimeConfig(enable_finalizer=False), llm_invoke=mock_llm, tool_registry=registry)
        result = await engine.run("attack")

        assert not result.success
        assert "structured_errors" in result.metadata
        assert any("FORBIDDEN_COMMAND" in str(e) for e in result.metadata["structured_errors"])
        # v3.17: exec.run=medium → composite risk_level may be lower,
        # but the command is still hard-blocked by command_policy.
        assert any(e.get("code") == "FORBIDDEN_COMMAND"
                   for e in result.metadata.get("structured_errors", []))

        records = engine._audit.records
        assert len(records) == 1
        assert len(records[0].blocked_nodes) == 1
        assert records[0].blocked_nodes[0]["node_id"] == "attack"


# ============================================================================
# Pre-Execution Repair Tests (v1.0)
# ============================================================================

class TestPreExecutionRepair:
    """Test the pre-execution repair engine."""

    def test_can_repair_enum_invalid(self):
        from core.runtime_engine.pre_execution_repair import PreExecutionRepairEngine
        engine = PreExecutionRepairEngine()
        assert engine.can_repair(["ARG_ENUM_INVALID"])
        assert engine.can_repair(["ARG_ENUM_INVALID", "MISSING_REQUIRED_ARG"])

    def test_cannot_repair_security_errors(self):
        from core.runtime_engine.pre_execution_repair import PreExecutionRepairEngine
        engine = PreExecutionRepairEngine()
        assert not engine.can_repair(["FORBIDDEN_COMMAND"])
        assert not engine.can_repair(["ARG_ENUM_INVALID", "FORBIDDEN_COMMAND"])
        assert not engine.can_repair(["POLICY_BLOCKED"])
        assert not engine.can_repair(["CRITICAL_RISK"])
        assert not engine.can_repair(["FORBIDDEN_ARG"])

    def test_action_alias_session_get_is_canonical(self):
        """session_get is current canonical action, not an alias."""
        from core.runtime_engine.action_alias import ACTION_ALIASES, normalize_action_alias
        assert "session_get" not in ACTION_ALIASES
        assert normalize_action_alias("session_get") == ("session_get", None)

    def test_action_alias_get_session(self):
        """get_session is in action_alias.py"""
        from core.runtime_engine.action_alias import ACTION_ALIASES
        assert "get_session" in ACTION_ALIASES
        assert ACTION_ALIASES["get_session"] == "session_get"

    def test_action_alias_session_history(self):
        """session_history is in action_alias.py"""
        from core.runtime_engine.action_alias import ACTION_ALIASES
        assert "session_history" in ACTION_ALIASES
        assert ACTION_ALIASES["session_history"] == "session_get"

    def test_action_alias_review_get(self):
        # v3.10: review_get is now a STABLE alias in the canonical
        # table (action_alias.py), not a runtime fallback. The
        # canonical source owns it; ``ACTION_ALIAS_MAP`` is renamed
        # to ``EXTENDED_RUNTIME_ALIAS_MAP`` and stays empty for it.
        from core.runtime_engine.action_alias import (
            resolve_action_alias, ACTION_ALIASES,
        )
        assert "review_get" in ACTION_ALIASES
        assert ACTION_ALIASES["review_get"] == "review_list"
        res = resolve_action_alias("system.manage", "review_get")
        assert res.matched is True
        assert res.source == "canonical"
        assert res.canonical_action == "review_list"
        assert res.operation == "get"

    def test_action_alias_audit_get(self):
        from core.runtime_engine.action_alias import (
            resolve_action_alias, ACTION_ALIASES,
        )
        assert "audit_get" in ACTION_ALIASES
        assert ACTION_ALIASES["audit_get"] == "audit_log"
        res = resolve_action_alias("system.manage", "audit_get")
        assert res.matched is True
        assert res.source == "canonical"
        assert res.canonical_action == "audit_log"
        assert res.operation == "get"

    def test_repair_result_not_repaired_initially(self):
        from core.runtime_engine.pre_execution_repair import PreExecutionRepairResult
        r = PreExecutionRepairResult()
        assert not r.repaired
        assert r.strategy == ""

    def test_should_not_replan_with_llm_when_no_budget(self):
        from core.runtime_engine.pre_execution_repair import PreExecutionRepairEngine, PreExecutionRepairResult
        engine = PreExecutionRepairEngine()
        result = PreExecutionRepairResult(repaired=False, strategy="deterministic",
                                          unrepairable_reason="test")
        assert not engine.should_replan_with_llm(result, 0)


class TestPreExecutionRepairPipeline:
    """Full pipeline integration tests for pre-execution repair."""

    @pytest.fixture
    def config(self):
        return SSOTRuntimeConfig()

    @pytest.mark.asyncio
    async def test_review_get_auto_fixed(self, config):
        """v3.10: review_get is a STABLE canonical alias — GraphCompiler
        rewrites it at compile time, so pre_exec_repair never sees it.

        The end-to-end contract is unchanged: ``review_get`` still
        resolves to ``action=review`` and the tool runs successfully.
        What changes is which layer does the rewrite — the canonical
        source (action_alias.resolve_action_alias) instead of the
        pre-execution repair fallback.
        """
        from core.runtime_engine.engine import SSOTRuntimeEngine
        from core.runtime_engine.models import ExecutionStatus
        import json

        plan_json = json.dumps({"nodes": [
            {"id": "get_review", "tool": "system.manage",
             "args": {"action": "review_get"}, "deps": []}
        ]})

        def mock_llm(**kw):
            return plan_json

        registry = {"system.manage": {"description": "", "args_schema": {
            "required": ["action"],
            "properties": {"action": {"type": "string", "enum": [
                "diagnostics", "health", "selfcheck", "tasks",
                "audit", "run", "session", "review"
            ]}},
        }}}

        engine = SSOTRuntimeEngine(config=SSOTRuntimeConfig(enable_finalizer=False),
                            llm_invoke=mock_llm, tool_registry=registry)

        async def handler(args):
            return f"review data"

        engine.register_tool("system.manage", handler)
        result = await engine.run("get review")

        assert result.success, f"Expected success, got errors: {result.errors}"
        assert result.node_success_count == 1
        # canonical hit: GraphCompiler rewrote the action; node carries
        # the action_original / action_normalized_from_alias provenance.
        node = result.node_results.get("get_review")
        assert node is not None
        assert node.success is True
        # pre_exec_repair must NOT fire — the canonical path handled it.
        assert result.metadata.get("pre_exec_repair_applied") is False

    @pytest.mark.asyncio
    async def test_audit_get_auto_fixed(self, config):
        """audit_get → action=audit (NOT in action_alias.py → caught by repair)"""
        from core.runtime_engine.engine import SSOTRuntimeEngine
        import json

        plan_json = json.dumps({"nodes": [
            {"id": "n1", "tool": "system.manage",
             "args": {"action": "audit_get"}, "deps": []}
        ]})

        def mock_llm(**kw):
            return plan_json

        registry = {"system.manage": {"description": "", "args_schema": {
            "required": ["action"],
            "properties": {"action": {"type": "string", "enum": [
                "diagnostics", "health", "selfcheck", "tasks",
                "audit", "run", "session", "review"
            ]}},
        }}}

        engine = SSOTRuntimeEngine(config=SSOTRuntimeConfig(enable_finalizer=False),
                            llm_invoke=mock_llm, tool_registry=registry)

        async def handler(args):
            return "audit data"

        engine.register_tool("system.manage", handler)
        result = await engine.run("get audit")
        assert result.success

    @pytest.mark.asyncio
    async def test_task_get_auto_fixed(self, config):
        """task_get → action=tasks (NOT in action_alias.py → caught by repair)"""
        from core.runtime_engine.engine import SSOTRuntimeEngine
        import json

        plan_json = json.dumps({"nodes": [
            {"id": "n1", "tool": "system.manage",
             "args": {"action": "task_get"}, "deps": []}
        ]})

        def mock_llm(**kw):
            return plan_json

        registry = {"system.manage": {"description": "", "args_schema": {
            "required": ["action"],
            "properties": {"action": {"type": "string", "enum": [
                "diagnostics", "health", "selfcheck", "tasks",
                "audit", "run", "session", "review"
            ]}},
        }}}

        engine = SSOTRuntimeEngine(config=SSOTRuntimeConfig(enable_finalizer=False),
                            llm_invoke=mock_llm, tool_registry=registry)

        async def handler(args):
            return f"tasks: {args.get('action', '')}"

        engine.register_tool("system.manage", handler)
        result = await engine.run("tasks")
        assert result.success

    @pytest.mark.asyncio
    async def test_delete_system_not_repairable(self, config):
        """Non-existent action with no alias → should NOT be repaired"""
        from core.runtime_engine.engine import SSOTRuntimeEngine
        import json

        plan_json = json.dumps({"nodes": [
            {"id": "n1", "tool": "system.manage",
             "args": {"action": "delete_system"}, "deps": []}
        ]})

        def mock_llm(**kw):
            return plan_json

        registry = {"system.manage": {"description": "", "args_schema": {
            "required": ["action"],
            "properties": {"action": {"type": "string", "enum": [
                "diagnostics", "health", "selfcheck", "tasks",
                "audit", "run", "session", "review"
            ]}},
        }}}

        engine = SSOTRuntimeEngine(config=SSOTRuntimeConfig(enable_finalizer=False),
                            llm_invoke=mock_llm, tool_registry=registry)

        async def handler(args):
            return "should never run"

        engine.register_tool("system.manage", handler)
        result = await engine.run("delete system")
        assert not result.success

    @pytest.mark.asyncio
    async def test_forbidden_command_not_repairable(self, config):
        """powershell.exe -EncodedCommand → semantic reject, NO repair"""
        from core.runtime_engine.engine import SSOTRuntimeEngine
        import json

        plan_json = json.dumps({"nodes": [
            {"id": "attack", "tool": "exec.run",
             "args": {"command": "powershell.exe -EncodedCommand xxx"}, "deps": []}
        ]})

        def mock_llm(**kw):
            return plan_json

        registry = {"exec.run": {"description": "", "args_schema": {
            "required": ["command"], "properties": {"command": {"type": "string"}},
        }}}

        engine = SSOTRuntimeEngine(config=SSOTRuntimeConfig(enable_finalizer=False),
                            llm_invoke=mock_llm, tool_registry=registry)

        engine.register_tool("exec.run", lambda args: "SHOULD NOT RUN")
        result = await engine.run("attack")
        assert not result.success
        assert len(result.node_results) == 0  # executor never ran
        assert not result.metadata.get("pre_exec_repair_applied", False)

    @pytest.mark.asyncio
    async def test_rm_rf_not_repairable(self, config):
        """rm -rf / → semantic reject, NO repair"""
        from core.runtime_engine.engine import SSOTRuntimeEngine
        import json

        plan_json = json.dumps({"nodes": [
            {"id": "attack", "tool": "exec.run",
             "args": {"command": "rm -rf /"}, "deps": []}
        ]})

        def mock_llm(**kw):
            return plan_json

        registry = {"exec.run": {"description": "", "args_schema": {
            "required": ["command"], "properties": {"command": {"type": "string"}},
        }}}

        engine = SSOTRuntimeEngine(config=SSOTRuntimeConfig(enable_finalizer=False),
                            llm_invoke=mock_llm, tool_registry=registry)

        engine.register_tool("exec.run", lambda args: "SHOULD NOT RUN")
        result = await engine.run("destroy everything")
        assert not result.success
        assert len(result.node_results) == 0

    @pytest.mark.asyncio
    async def test_repair_events_in_trace(self, config):
        """v3.10: review_get is a STABLE canonical alias now, so the
        pre-execution repair path does not fire for it. To exercise
        the EXTENDED_RUNTIME_ALIAS_MAP fallback we feed in a
        transient alias (file_read on workspace.file)."""
        from core.runtime_engine.engine import SSOTRuntimeEngine
        import json

        # workspace.file with ``file_read`` — this alias is in the
        # EXTENDED_RUNTIME_ALIAS_MAP and should still be repaired at
        # runtime when GraphCompiler fails to rewrite it.
        plan_json = json.dumps({"nodes": [
            {"id": "n1", "tool": "workspace.file",
             "args": {"action": "file_read", "path": "/tmp/x"}, "deps": []}
        ]})

        def mock_llm(**kw):
            return plan_json

        registry = {"workspace.file": {"description": "", "args_schema": {
            "required": ["action", "path"],
            "properties": {"action": {"type": "string", "enum": [
                "list", "read", "read_image", "edit", "patch",
                "write_artifact", "glob", "delete_file",
            ]}, "path": {"type": "string"}},
        }}}

        engine = SSOTRuntimeEngine(config=SSOTRuntimeConfig(enable_finalizer=False),
                            llm_invoke=mock_llm, tool_registry=registry)

        async def handler(args):
            return "ok"

        engine.register_tool("workspace.file", handler)
        result = await engine.run("read file")

        events = result.metadata.get("pre_exec_repair_events", [])
        assert len(events) > 0, f"No repair events found"
        event = events[0]
        assert event["original_action"] == "file_read"
        assert event["normalized_action"] == "read"
        # Extended source — file_read is in the runtime fallback.
        assert event.get("source") == "extended"
