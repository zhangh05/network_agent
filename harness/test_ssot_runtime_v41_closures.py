"""SSOT Runtime v4.1 — 3 system closure tests.

Covers:
  1. Diagnostic Loss Closure (error_code never lost)
  2. Causal Ordering Closure (causal_index, not created_at)
  3. Schema Enforcement Closure (PlanSchema.validate_raw)
"""

import json
import pytest
from types import SimpleNamespace

from core.runtime_engine.tool_runtime import (
    resolve_tool_outcome,
    _normalize_result,
    _STATUS_SUCCESS,
    _STATUS_FAIL,
)
from core.runtime_engine.models import ToolResult, ExecutionNode
from core.runtime_engine.planner import PlanSchema, SchemaValidationError
from core.runtime_engine.runtime_contracts import (
    ExecutionContract,
    ExecutionObligationViolation,
    ExecutionSemanticsContract,
    CausalIndexGuard,
    CausalityViolationError,
    ContextSnapshot,
    assert_error_code_usage,
)
from core.runtime_engine.engine import detect_task_intent


# ============================================================================
# 1. Diagnostic Loss Closure
# ============================================================================

class TestDiagnosticLossClosure:
    """error_code_raw/error_code_norm are never lost in the pipeline."""

    def test_ok_false_preserves_code(self):
        r = {"ok": False, "error_code": "INPUT_MISSING", "errors": ["missing field"]}
        status, code, _ = resolve_tool_outcome(r)
        assert status == _STATUS_FAIL
        assert code == "INPUT_MISSING"

    def test_ok_false_no_code_gets_default(self):
        r = {"ok": False, "errors": ["timeout"]}
        status, code, _ = resolve_tool_outcome(r)
        assert status == _STATUS_FAIL
        assert code == "TOOL_RETURNED_NOT_OK"

    def test_legacy_success_false_gets_failure_code(self):
        """Legacy success=False path no longer returns None for error_code."""
        r = {"success": False, "error": "boom"}
        status, code, _ = resolve_tool_outcome(r)
        assert status == _STATUS_FAIL
        # v4.1: legacy failure → "LEGACY_FAILURE"
        assert code == "LEGACY_FAILURE"

    def test_legacy_success_false_with_code(self):
        r = {"success": False, "error_code": "MY_ERR"}
        status, code, _ = resolve_tool_outcome(r)
        assert status == _STATUS_FAIL
        assert code == "MY_ERR"

    def test_normalize_result_populates_error_code_fields(self):
        """_normalize_result sets error_code_raw and error_code_norm."""
        node = ExecutionNode(id="n1", tool="test.tool", args={}, deps=[])
        r = {"ok": False, "error_code": "RATE_LIMITED", "code": "429"}
        tr = _normalize_result(node, r, 100.0)
        assert tr.success is False
        assert tr.error_code_raw == "RATE_LIMITED"
        assert tr.error_code_norm == "RATE_LIMITED"
        assert tr.error_code == "RATE_LIMITED"

    def test_legacy_failure_has_norm(self):
        """Legacy success=False → error_code_norm = LEGACY_FAILURE."""
        node = ExecutionNode(id="n1", tool="test.tool", args={}, deps=[])
        r = {"success": False, "error": "connection refused"}
        tr = _normalize_result(node, r, 50.0)
        assert tr.success is False
        assert tr.error_code_norm == "LEGACY_FAILURE"
        assert tr.error_code == "LEGACY_FAILURE"

    def test_success_case_no_error_code(self):
        r = {"ok": True, "data": {"x": 1}}
        status, code, _ = resolve_tool_outcome(r)
        assert status == _STATUS_SUCCESS
        assert code is None

    def test_dict_without_ok_is_success(self):
        r = {"data": "value"}
        status, code, _ = resolve_tool_outcome(r)
        assert status == _STATUS_SUCCESS

    def test_retry_can_distinguish_error_types(self):
        """Different error_codes produce different normalised codes."""
        assert resolve_tool_outcome({"ok": False})[1] == "TOOL_RETURNED_NOT_OK"
        assert resolve_tool_outcome({"ok": False, "error_code": "TIMEOUT"})[1] == "TIMEOUT"
        assert resolve_tool_outcome({"success": False})[1] == "LEGACY_FAILURE"


# ============================================================================
# 2. Causal Ordering Closure
# ============================================================================

class TestCausalOrderingClosure:
    """causal_index replaces created_at for event ordering."""

    def test_build_context_events_uses_causal_index(self):
        from agent.runtime.ssot_runtime import build_context_events

        session = SimpleNamespace(
            session_id="test-causal",
            workspace_id="test",
            history=[
                SimpleNamespace(role="user", content="hello"),
                SimpleNamespace(role="assistant", content="hi"),
            ],
        )
        events = build_context_events(session)
        assert len(events) >= 2
        # All events should have _causal_index
        for ev in events:
            assert "_causal_index" in ev

    def test_populate_from_session_uses_causal_order(self):
        from agent.runtime.ssot_runtime import _inject_conversation_context

        session = SimpleNamespace(
            session_id="test-co",
            workspace_id="test",
            history=[
                SimpleNamespace(role="user", content="msg 1"),
                SimpleNamespace(role="assistant", content="reply 1"),
                SimpleNamespace(role="user", content="msg 2"),
                SimpleNamespace(role="assistant", content="reply 2"),
            ],
        )
        meta = {}
        _inject_conversation_context(session, meta)
        cc = meta.get("conversation_context")
        assert cc is not None
        # Recent messages should maintain causal order (oldest first)
        recent = cc.recent_messages
        roles = [m["role"] for m in recent]
        # First message in recent window should be user, last should be assistant
        if len(recent) >= 4:
            assert roles[0] == "user"
            assert roles[-1] == "assistant"

    def test_contracts_ordered(self):
        """v4.1 contracts are in place."""
        assert ExecutionContract.CONTEXT_CAUSAL_ORDER_ONLY is True


# ============================================================================
# 3. Schema Enforcement Closure
# ============================================================================

class TestSchemaEnforcementClosure:
    """PlanSchema.validate_raw() strictly validates planner output."""

    def test_valid_plan_passes(self):
        data = {
            "nodes": [
                {"id": "n1", "tool": "exec.run", "args": {"cmd": "ls"}, "deps": []},
            ]
        }
        nodes = PlanSchema.validate_raw(data)
        assert len(nodes) == 1
        assert nodes[0].id == "n1"
        assert nodes[0].tool == "exec.run"

    def test_empty_nodes_is_execution_obligation(self):
        data = {"nodes": []}
        with pytest.raises(ExecutionObligationViolation):
            PlanSchema.validate_raw(data, "巡检 CMDB", True)

    def test_unknown_top_level_keys_raises_schema_error(self):
        data = {"steps": [], "tool_calls": []}
        with pytest.raises(SchemaValidationError):
            PlanSchema.validate_raw(data)

    def test_nodes_not_list_raises(self):
        data = {"nodes": "not a list"}
        with pytest.raises(SchemaValidationError):
            PlanSchema.validate_raw(data)

    def test_node_not_dict_raises(self):
        data = {"nodes": ["not a dict"]}
        with pytest.raises(SchemaValidationError):
            PlanSchema.validate_raw(data)

    def test_null_tool_raises(self):
        data = {"nodes": [{"id": "n1", "tool": None, "args": {}}]}
        with pytest.raises(SchemaValidationError):
            PlanSchema.validate_raw(data)

    def test_missing_tool_raises(self):
        data = {"nodes": [{"id": "n1", "args": {}}]}
        with pytest.raises(SchemaValidationError):
            PlanSchema.validate_raw(data)

    def test_non_string_tool_raises(self):
        data = {"nodes": [{"id": "n1", "tool": 123, "args": {}}]}
        with pytest.raises(SchemaValidationError):
            PlanSchema.validate_raw(data)

    def test_non_dict_args_raises(self):
        data = {"nodes": [{"id": "n1", "tool": "exec.run", "args": "bad"}]}
        with pytest.raises(SchemaValidationError):
            PlanSchema.validate_raw(data)

    def test_missing_id_raises(self):
        data = {"nodes": [{"tool": "exec.run", "args": {}}]}
        with pytest.raises(SchemaValidationError):
            PlanSchema.validate_raw(data)

    def test_optional_deps(self):
        data = {
            "nodes": [
                {"id": "n1", "tool": "exec.run", "args": {}},
                {"id": "n2", "tool": "config.manage", "args": {}, "deps": ["n1"]},
            ]
        }
        nodes = PlanSchema.validate_raw(data)
        assert len(nodes) == 2

    def test_non_list_deps_raises(self):
        data = {
            "nodes": [
                {"id": "n1", "tool": "exec.run", "args": {}, "deps": "nope"},
            ]
        }
        with pytest.raises(SchemaValidationError):
            PlanSchema.validate_raw(data)

    def test_plan_with_final_response_passes(self):
        data = {
            "nodes": [],
            "final_response": "OSPF is a link-state routing protocol.",
        }
        nodes = PlanSchema.validate_raw(data)
        assert nodes == []


# ============================================================================
# 4. Contract Assertions
# ============================================================================

class TestV41Contracts:
    """v4.1 contracts are in effect."""

    def test_all_six_contracts(self):
        assert ExecutionContract.TOOL_TRUTH_SINGLE_SOURCE
        assert ExecutionContract.CONTEXT_EVENT_STREAM_ONLY
        assert ExecutionContract.EXECUTION_OBLIGATION_ENFORCED
        assert ExecutionContract.CONTEXT_CAUSAL_ORDER_ONLY
        assert ExecutionContract.PLAN_STRICT_SCHEMA_ENFORCED
        assert ExecutionContract.DIAGNOSTIC_PRESERVATION_REQUIRED


# ============================================================================
# v6: Boundary Convergence Tests
# ============================================================================

class TestV6ErrorCodeBoundary:
    """error_code_norm is the sole system-decision code."""

    def test_assert_error_code_usage_passes_on_valid(self):
        node = ExecutionNode(id="n1", tool="t", args={}, deps=[])
        tr = _normalize_result(node, {"ok": False, "error_code": "E1"}, 10.0)
        assert_error_code_usage(tr)  # should not raise

    def test_error_code_raw_is_preserved(self):
        node = ExecutionNode(id="n1", tool="t", args={}, deps=[])
        tr = _normalize_result(node, {"ok": False, "error_code": "CUSTOM"}, 10.0)
        assert tr.error_code_raw == "CUSTOM"
        assert tr.error_code_norm == "CUSTOM"

    def test_legacy_failure_has_norm_not_none(self):
        node = ExecutionNode(id="n1", tool="t", args={}, deps=[])
        tr = _normalize_result(node, {"success": False}, 10.0)
        assert tr.error_code_norm is not None
        assert tr.error_code_norm == "LEGACY_FAILURE"


class TestV6CausalClockConvergence:
    """GlobalCausalityClock enforces deterministic ordering."""

    def test_causal_index_present_on_all_events(self):
        from agent.runtime.ssot_runtime import build_context_events
        session = SimpleNamespace(
            session_id="test-v6", workspace_id="test",
            history=[
                SimpleNamespace(role="user", content="test"),
                SimpleNamespace(role="assistant", content="ok"),
            ],
        )
        events = build_context_events(session)
        for ev in events:
            assert "_causal_index" in ev, f"Missing causal_index in {ev.get('role')}"

    def test_causal_index_guard_validates(self):
        valid = [{"_causal_index": 1, "role": "user", "content": "hi"}]
        CausalIndexGuard.validate(valid)  # no raise

    def test_causal_index_guard_raises(self):
        invalid = [{"role": "user", "content": "hi"}]
        with pytest.raises(CausalityViolationError):
            CausalIndexGuard.validate(invalid)


class TestV6ContextSnapshot:
    """ContextSnapshot is immutable after build."""

    def test_snapshot_is_iterable(self):
        events = [{"role": "user", "content": "hi"}]
        snap = ContextSnapshot(events)
        assert len(snap) == 1
        assert snap[0]["content"] == "hi"

    def test_snapshot_converts_to_list(self):
        events = [{"role": "user", "content": "hi"}]
        snap = ContextSnapshot(events)
        lst = list(snap)
        assert len(lst) == 1


class TestV6SemanticsContract:
    """ExecutionSemanticsContract v6 flags."""

    def test_all_four_contracts(self):
        assert ExecutionSemanticsContract.SINGLE_TRUTH_TOOL_RESULT
        assert ExecutionSemanticsContract.SINGLE_CONTEXT_SOURCE
        assert ExecutionSemanticsContract.CAUSAL_ORDER_STRICT
        assert ExecutionSemanticsContract.SCHEMA_EXECUTION_UNIFIED
