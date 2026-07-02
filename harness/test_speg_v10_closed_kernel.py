"""SPEG v10 Closed Execution Kernel — DecisionGraph, ContextSeal,
ExecutionReplay, and ContractBoundary.
"""

import json
import pytest
from types import SimpleNamespace

from speg_engine.decision_graph import DecisionGraph, DecisionNode
from speg_engine.context_seal import ContextSeal
from speg_engine.execution_replay import (
    ExecutionTrace,
    ExecutionTraceEvent,
    ExecutionReplay,
    VerifyReplayMode,
)
from speg_engine.runtime_contracts import ContractBoundary
from speg_engine.runtime_stability import IssueCollector, Severity, IssueCategory


# ============================================================================
# DecisionGraph
# ============================================================================

class TestDecisionGraph:
    """Single decision entry — routes all failure scenarios."""

    def test_clean_report_routes_to_run(self):
        dg = DecisionGraph()
        r = _make_report(critical=0, high=0)
        node = dg.decide(None, r)
        assert node.action == "RUN"

    def test_critical_routes_to_stop(self):
        dg = DecisionGraph()
        r = _make_report(critical=1, high=0)
        node = dg.decide(None, r)
        assert node.action == "STOP"

    def test_high_routes_to_degrade(self):
        dg = DecisionGraph()
        r = _make_report(critical=0, high=1)
        node = dg.decide(None, r)
        assert node.action == "DEGRADE"

    def test_retryable_planner_scope(self):
        dg = DecisionGraph()
        r = SimpleNamespace(critical_count=0, high_count=0,
                            recoverable=True, source="PLANNER_ERROR")
        node = dg.decide(None, r)
        assert node.action == "RETRY_PLANNER"

    def test_retryable_tool_scope(self):
        dg = DecisionGraph()
        r = SimpleNamespace(critical_count=0, high_count=0,
                            recoverable=True, source="TOOL_FAILURE")
        node = dg.decide(None, r)
        assert node.action == "RETRY_TOOL"

    def test_retryable_unknown_scope(self):
        dg = DecisionGraph()
        r = SimpleNamespace(critical_count=0, high_count=0,
                            recoverable=True, source="")
        node = dg.decide(None, r)
        assert node.action == "RETRY_FULL"

    def test_decision_graph_traceable(self):
        dg = DecisionGraph()
        r = _make_report(critical=1, high=0)
        dg.decide(None, r)
        dg.decide(None, _make_report(0, 0))
        trace = dg.to_trace()
        assert len(trace) == 2
        assert trace[0]["action"] == "STOP"
        assert trace[1]["action"] == "RUN"


# ============================================================================
# ContextSeal
# ============================================================================

class TestContextSeal:
    """Context is sealed and verifiable."""

    def test_seal_and_verify(self):
        events = [{"role": "user", "content": "hi"}]
        sealed = ContextSeal.seal(events)
        assert sealed["sealed"] is True
        assert ContextSeal.verify(sealed) is True

    def test_tampered_verification_fails(self):
        events = [{"role": "user", "content": "hi"}]
        sealed = ContextSeal.seal(events)
        sealed["snapshot"] = [{"role": "user", "content": "hacked"}]
        assert ContextSeal.verify(sealed) is False

    def test_unseal_returns_snapshot(self):
        events = [{"role": "user", "content": "test"}]
        sealed = ContextSeal.seal(events)
        snap = ContextSeal.unseal(sealed)
        assert snap == events

    def test_unseal_none_on_bad_seal(self):
        sealed = {"sealed": True, "snapshot": [], "hash": "bad"}
        assert ContextSeal.unseal(sealed) is None

    def test_verify_empty(self):
        sealed = ContextSeal.seal([])
        assert ContextSeal.verify(sealed) is True


# ============================================================================
# ExecutionReplay
# ============================================================================

class TestExecutionReplay:
    """Execution trace is fully replayable."""

    def test_valid_trace_replays(self):
        trace = ExecutionTrace()
        trace.record(ExecutionTraceEvent(1, "run", "RUNNING", "RUNNING", "abc"))
        trace.record(ExecutionTraceEvent(2, "run", "RUNNING", "RUNNING", "def"))
        assert ExecutionReplay.replay(trace) is True

    def test_non_monotonic_causal_fails(self):
        trace = ExecutionTrace()
        trace.record(ExecutionTraceEvent(2, "run", "RUNNING", "RUNNING", "a"))
        trace.record(ExecutionTraceEvent(1, "run", "RUNNING", "RUNNING", "b"))
        with pytest.raises(AssertionError):
            ExecutionReplay.replay(trace)

    def test_missing_causal_index_fails(self):
        trace = ExecutionTrace()
        trace.record(ExecutionTraceEvent(None, "run", "RUNNING", "RUNNING", "a"))
        with pytest.raises(AssertionError):
            ExecutionReplay.replay(trace)

    def test_invalid_state_fails(self):
        trace = ExecutionTrace()
        trace.record(ExecutionTraceEvent(1, "run", "INVALID", "RUNNING", "a"))
        with pytest.raises(AssertionError):
            ExecutionReplay.replay(trace)

    def test_trace_event_serialization(self):
        ev = ExecutionTraceEvent(1, "critical_gate", "RUNNING", "TERMINAL", "h")
        d = ev.to_dict()
        assert d["causal_index"] == 1
        assert d["state_before"] == "RUNNING"
        assert d["state_after"] == "TERMINAL"


# ============================================================================
# ContractBoundary
# ============================================================================

class TestContractBoundary:
    """Contracts enforced at 4 mandatory checkpoints."""

    def test_all_layers_defined(self):
        assert len(ContractBoundary.ENFORCE_AT) == 4
        assert "engine_entry" in ContractBoundary.ENFORCE_AT
        assert "decision_graph" in ContractBoundary.ENFORCE_AT
        assert "tool_runtime" in ContractBoundary.ENFORCE_AT
        assert "finalizer" in ContractBoundary.ENFORCE_AT

    def test_validate_all_sets_hits(self):
        ctx = SimpleNamespace(extras={})
        ContractBoundary.validate_all(ctx)
        hits = ctx.extras["contract_boundary_hits"]
        for point in ContractBoundary.ENFORCE_AT:
            assert hits[point] is True

    def test_all_validated_true_after_validate_all(self):
        ctx = SimpleNamespace(extras={})
        ContractBoundary.validate_all(ctx)
        assert ContractBoundary.all_validated(ctx) is True

    def test_not_validated_false(self):
        ctx = SimpleNamespace(extras={})
        assert ContractBoundary.all_validated(ctx) is False


def _make_report(critical=0, high=0):
    c = IssueCollector()
    if critical > 0:
        c.add(Severity.CRITICAL, IssueCategory.CONTRACT, "t", "critical")
    if high > 0:
        c.add(Severity.HIGH, IssueCategory.TOOL, "t", "high")
    return c


# ============================================================================
# v10.1 additions
# ============================================================================

from speg_engine.decision_graph import DecisionPolicyResolver, DecisionPolicySpec


class TestV101DeclarativeRuleResolution:
    """DecisionGraph uses purely declarative rule matching."""

    def test_critical_matches(self):
        r = _make_report(critical=1, high=0)
        action, cond, _ = DecisionPolicyResolver.resolve_with_trace(r)
        assert action == "STOP"
        assert cond == "CRITICAL"

    def test_high_matches(self):
        r = _make_report(critical=0, high=1)
        action, _, _ = DecisionPolicyResolver.resolve_with_trace(r)
        assert action == "DEGRADE"

    def test_default_matches(self):
        r = _make_report(critical=0, high=0)
        action, _, _ = DecisionPolicyResolver.resolve_with_trace(r)
        assert action == "RUN"

    def test_retryable_planner(self):
        r = SimpleNamespace(critical_count=0, high_count=0,
                            recoverable=True, source="PLANNER")
        action, cond, _ = DecisionPolicyResolver.resolve_with_trace(r)
        assert action == "RETRY_PLANNER"
        assert "PLANNER" in cond

    def test_retryable_tool(self):
        r = SimpleNamespace(critical_count=0, high_count=0,
                            recoverable=True, source="TOOL")
        action, _, _ = DecisionPolicyResolver.resolve_with_trace(r)
        assert action == "RETRY_TOOL"

    def test_rules_in_correct_order(self):
        # critical should be checked before high
        r = _make_report(critical=1, high=1)
        action, _, _ = DecisionPolicyResolver.resolve_with_trace(r)
        assert action == "STOP"  # CRITICAL wins over HIGH

    def test_no_if_else_in_matching(self):
        """Verify the resolver is purely rule-driven."""
        trace = DecisionPolicyResolver.resolve_with_trace(_make_report(0, 0))[2]
        assert len(trace) == len(DecisionPolicySpec)
        assert trace[-1]["condition"] == "DEFAULT"


class TestV101CanonicalSerializer:
    """ContextSeal uses canonical serialization."""

    def test_canonical_is_deterministic(self):
        from speg_engine.context_seal import canonical_serialize, ContextSeal
        a = canonical_serialize([{"key": "val"}])
        b = canonical_serialize([{"key": "val"}])
        assert a == b

    def test_seal_with_canonical(self):
        from speg_engine.context_seal import ContextSeal
        s1 = ContextSeal.seal([{"a": 1}])
        s2 = ContextSeal.seal([{"a": 1}])
        assert s1["hash"] == s2["hash"]


class TestV101TraceIdentity:
    """ExecutionTrace has canonical identity hash."""

    def test_identity_is_deterministic(self):
        t1 = ExecutionTrace()
        t1.record(ExecutionTraceEvent(1, "a", "RUNNING", "RUNNING", "h"))
        t2 = ExecutionTrace()
        t2.record(ExecutionTraceEvent(1, "a", "RUNNING", "RUNNING", "h"))
        assert t1.identity == t2.identity

    def test_identity_changes_with_content(self):
        t1 = ExecutionTrace()
        t1.record(ExecutionTraceEvent(1, "a", "RUNNING", "RUNNING", "h1"))
        t2 = ExecutionTrace()
        t2.record(ExecutionTraceEvent(1, "a", "RUNNING", "RUNNING", "h2"))
        assert t1.identity != t2.identity


class TestV101VerifyReplayMode:
    """VerifyReplayMode validates without executing tools."""

    def test_verify_mode_valid(self):
        trace = ExecutionTrace()
        trace.record(ExecutionTraceEvent(1, "r", "RUNNING", "RUNNING", "h"))
        result = VerifyReplayMode.verify(trace)
        assert result["valid"] is True
        assert "identity" in result

    def test_verify_mode_invalid(self):
        trace = ExecutionTrace()
        trace.record(ExecutionTraceEvent(1, "r", "RUNNING", "RUNNING", "h"))
        trace.record(ExecutionTraceEvent(0, "r", "RUNNING", "RUNNING", "h"))
        result = VerifyReplayMode.verify(trace)
        assert result["valid"] is False


class TestV101DependencyValidation:
    """Replay validates DAG dependencies."""

    def test_dependencies_resolved_passes(self):
        trace = ExecutionTrace()
        trace.record(ExecutionTraceEvent(1, "r", "RUNNING", "RUNNING", "h",
                                         dependencies_resolved=True))
        assert ExecutionReplay.replay(trace) is True

    def test_dependencies_unresolved_fails(self):
        trace = ExecutionTrace()
        trace.record(ExecutionTraceEvent(1, "r", "RUNNING", "RUNNING", "h",
                                         dependencies_resolved=False))
        with pytest.raises(AssertionError):
            ExecutionReplay.replay(trace)


class TestV101ContractDecorator:
    """ContractBoundary decorator enforces pre-validation."""

    def test_decorator_function_defined(self):
        from speg_engine.runtime_contracts import enforce_contract_boundary
        assert callable(enforce_contract_boundary)

    def test_validate_all_still_works(self):
        ctx = SimpleNamespace(extras={})
        ContractBoundary.validate_all(ctx)
        assert ContractBoundary.all_validated(ctx)
