"""Tests for SPEG action-alias normalization (v3.10).

Covers:
  * canonical aliases are normalized by GraphCompiler BEFORE
    semantic_validator runs
  * audit / risk / trace surfaces carry the original token +
    canonical token so the operator can spot planner drift
  * truly unknown actions (``delete_system``) are still rejected
    by the canonical-enum semantic check
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# 1. Plan output action=session_get -> normalized to "session"
# ---------------------------------------------------------------------------

def test_session_get_alias_normalizes_to_canonical_session():
    from speg_engine.action_alias import normalize_action_alias
    canonical, original = normalize_action_alias("session_get")
    assert canonical == "session"
    assert original == "session_get"


def test_get_session_alias_normalizes_to_session():
    from speg_engine.action_alias import normalize_action_alias
    canonical, original = normalize_action_alias("get_session")
    assert canonical == "session"
    assert original == "get_session"


def test_history_get_session_history_aliases_normalize():
    from speg_engine.action_alias import normalize_action_alias
    for raw, expected_canonical in (
        ("session_history", "session"),
        ("history_get", "session"),
        ("session_list", "session"),
        ("list_sessions", "session"),
    ):
        canonical, original = normalize_action_alias(raw)
        assert canonical == expected_canonical, raw
        assert original == raw, raw


def test_unrelated_aliases_normalize_for_other_tools():
    from speg_engine.action_alias import normalize_action_alias
    # workspace.file
    assert normalize_action_alias("ls")[:2] == ("list", "ls")
    assert normalize_action_alias("cat")[:2] == ("read", "cat")
    # knowledge.manage
    assert normalize_action_alias("knowledge_get")[:2] == ("read", "knowledge_get")
    assert normalize_action_alias("knowledge_search")[:2] == ("search", "knowledge_search")
    # agent.manage
    assert normalize_action_alias("agent_spawn")[:2] == ("spawn", "agent_spawn")
    assert normalize_action_alias("agent_list")[:2] == ("role_list", "agent_list")


def test_unknown_action_returns_none_canonical():
    """Truly invalid actions must surface None — not silently mapped."""
    from speg_engine.action_alias import normalize_action_alias
    canonical, original = normalize_action_alias("delete_system")
    assert canonical == "delete_system"  # not in alias map → token returned as-is
    assert original is None
    # The semantic validator is the gate that rejects this later.


# ---------------------------------------------------------------------------
# 2. End-to-end: GraphCompiler rewrites & node carries the bookkeeping,
#    semantic_validator passes on the rewritten value
# ---------------------------------------------------------------------------

def _make_plan_node(*, node_id, tool, action, deps=None):
    return {
        "id": node_id,
        "tool": tool,
        "args": {"action": action},
        "deps": list(deps or []),
    }


def test_graph_compiler_normalizes_alias_on_system_manage():
    from speg_engine.graph_compiler import GraphCompiler
    from speg_engine.models import SPEGConfig

    plan = [
        type("PlanNode", (), _make_plan_node(
            node_id="n1",
            tool="system.manage",
            action="session_get",
        ))(),
    ]
    dag = GraphCompiler(SPEGConfig()).compile(plan)

    assert dag.total_nodes == 1
    node = dag.nodes[0]
    # Args were rewritten to canonical.
    assert node.args["action"] == "session"
    # Bookkeeping present on the node.
    assert node.action_original == "session_get"
    assert node.action_normalized_from_alias is True


def test_graph_compiler_does_not_normalize_canonical_token():
    """A canonical ``session`` action on system.manage must NOT mark
    the node as alias-normalized (origin == canonical → no drift)."""
    from speg_engine.graph_compiler import GraphCompiler
    from speg_engine.models import SPEGConfig

    plan = [
        type("PlanNode", (), _make_plan_node(
            node_id="n1",
            tool="system.manage",
            action="session",
        ))(),
    ]
    dag = GraphCompiler(SPEGConfig()).compile(plan)
    node = dag.nodes[0]
    assert node.args["action"] == "session"
    assert node.action_original == ""
    assert node.action_normalized_from_alias is False


# ---------------------------------------------------------------------------
# 3. End-to-end: a normalized alias passes semantic validation
# ---------------------------------------------------------------------------

def test_semantic_validator_accepts_normalized_session_get_on_system_manage():
    from speg_engine.graph_compiler import GraphCompiler
    from speg_engine.models import SPEGConfig
    from speg_engine.semantic_validator import SemanticValidator

    plan = [
        type("PlanNode", (), _make_plan_node(
            node_id="n1",
            tool="system.manage",
            action="session_get",
        ))(),
    ]
    dag = GraphCompiler(SPEGConfig()).compile(plan)
    result = SemanticValidator().validate(dag)
    assert result.valid, (
        "After alias normalization, ``action=session`` on system.manage "
        f"must be canonical — got errors: {[e.message for e in result.errors]}"
    )


def test_semantic_validator_accepts_get_session_alias():
    """Same as above for a different alias — proves the normalization
    layer applies uniformly, not just to one spelling."""
    from speg_engine.graph_compiler import GraphCompiler
    from speg_engine.models import SPEGConfig
    from speg_engine.semantic_validator import SemanticValidator

    plan = [
        type("PlanNode", (), _make_plan_node(
            node_id="n1",
            tool="system.manage",
            action="get_session",
        ))(),
    ]
    dag = GraphCompiler(SPEGConfig()).compile(plan)
    result = SemanticValidator().validate(dag)
    assert result.valid


# ---------------------------------------------------------------------------
# 4. Truly bogus action (``delete_system``) must STILL be rejected
# ---------------------------------------------------------------------------

def test_unknown_action_delete_system_is_rejected_by_semantic_validator():
    from speg_engine.graph_compiler import GraphCompiler
    from speg_engine.models import SPEGConfig
    from speg_engine.semantic_validator import SemanticValidator

    plan = [
        type("PlanNode", (), _make_plan_node(
            node_id="n1",
            tool="system.manage",
            action="delete_system",  # not in alias table, not in canonical enum
        ))(),
    ]
    dag = GraphCompiler(SPEGConfig()).compile(plan)
    # GraphCompiler sees no alias hit, leaves args["action"]
    # untouched, no bookkeeping.
    assert dag.nodes[0].args["action"] == "delete_system"
    assert dag.nodes[0].action_normalized_from_alias is False

    result = SemanticValidator().validate(dag)
    assert not result.valid
    error_messages = [e.message for e in result.errors]
    assert any("delete_system" in m for m in error_messages), error_messages
    assert any("enum" in m.lower() for m in error_messages), error_messages


# ---------------------------------------------------------------------------
# 5. RiskPolicy surfaces alias provenance in its structured output
# ---------------------------------------------------------------------------

def test_risk_policy_records_alias_normalizations():
    from speg_engine.graph_compiler import GraphCompiler
    from speg_engine.models import SPEGConfig
    from speg_engine.risk_policy import RiskPolicyEngine

    plan = [
        type("PlanNode", (), _make_plan_node(
            node_id="n1",
            tool="system.manage",
            action="get_session",
        ))(),
    ]
    dag = GraphCompiler(SPEGConfig()).compile(plan)
    assessment = RiskPolicyEngine().assess(dag)
    assert assessment.safe_to_run
    assert len(assessment.alias_normalizations) == 1, assessment.alias_normalizations
    entry = assessment.alias_normalizations[0]
    assert entry["node_id"] == "n1"
    assert entry["action_original"] == "get_session"
    assert entry["action_normalized"] == "session"


# ---------------------------------------------------------------------------
# 6. AuditLogger writes the original + normalized fields per node
# ---------------------------------------------------------------------------

def test_audit_logger_records_action_original_and_normalized():
    from speg_engine.audit import AuditLogger
    from speg_engine.graph_compiler import GraphCompiler
    from speg_engine.models import ExecutionNode, ExecutionStatus, SPEGConfig, StatelessContext

    plan = [
        type("PlanNode", (), _make_plan_node(
            node_id="n1",
            tool="system.manage",
            action="session_get",
        ))(),
    ]
    dag = GraphCompiler(SPEGConfig()).compile(plan)

    # Mark the node success so it lands in ``executed_nodes``.
    dag.nodes[0].status = ExecutionStatus.SUCCESS
    node_results = {
        "n1": type("ToolResult", (), {
            "node_id": "n1", "tool": "system.manage",
            "success": True, "data": {}, "error": None,
            "latency_ms": 5.0, "retry_count": 0,
        })(),
    }
    ctx = StatelessContext(
        workspace_id="ws_test",
        session_id="sess_test",
        request_id="req_test",
        user_input="get session history",
    )
    record = AuditLogger().create_record(
        ctx, dag, node_results,
        risk_level="low", approval_required=False,
        llm_call_count=1, duration_ms=100.0,
    )
    assert len(record.executed_nodes) == 1
    node_entry = record.executed_nodes[0]
    assert node_entry["action_original"] == "session_get"
    assert node_entry["action_normalized_from_alias"] is True


# ---------------------------------------------------------------------------
# 7. TraceCollector.add_node_span carries the same provenance
# ---------------------------------------------------------------------------

def test_trace_node_span_records_alias_metadata():
    from speg_engine.graph_compiler import GraphCompiler
    from speg_engine.models import SPEGConfig
    from speg_engine.trace import TraceCollector

    plan = [
        type("PlanNode", (), _make_plan_node(
            node_id="n1",
            tool="system.manage",
            action="history_get",
        ))(),
    ]
    dag = GraphCompiler(SPEGConfig()).compile(plan)
    tracer = TraceCollector()
    span_clock = tracer.add_node_span(dag.nodes[0])
    # SpanClock wraps a TraceSpan; metadata sits on the inner span.
    md = span_clock.span.metadata or {}
    assert md.get("action_original") == "history_get"
    assert md.get("action_normalized") == "session"
    assert md.get("normalized_from_alias") is True


# ---------------------------------------------------------------------------
# 8. SPEGResult.metadata propagates the per-node summary
# ---------------------------------------------------------------------------

def test_speg_result_metadata_collects_alias_drift_summary():
    """The SPEGResult envelope exposes ``metadata.alias_normalizations``."""
    from speg_engine.action_alias import ACTION_ALIASES
    # Verify the table grows by exactly the documented set.
    expected_session_aliases = {
        "session_get", "get_session", "session_history",
        "history_get", "session_list", "list_sessions",
    }
    assert expected_session_aliases.issubset(ACTION_ALIASES.keys())
