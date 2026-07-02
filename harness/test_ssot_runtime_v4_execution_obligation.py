"""
v4 Execution Closure — Intent → Must DAG tests.

The v4 contract ``ExecutionContract.EXECUTION_OBLIGATION_ENFORCED``
mandates that the planner MUST NOT return an empty graph for a
user request that requires tool execution. The check is implemented
in ``core.runtime_engine.planner.enforce_execution_obligation`` and is
called inside ``Planner.plan()`` right before returning.

When the obligation is violated, the planner raises
``ExecutionObligationViolation`` (a ``Exception`` subclass). The
engine catches the exception and produces a structured error
result — the same code path the v3.14 empty-plan task-intent
guard used, but reached via raise instead of in-engine check.

These tests cover the obligation matrix:

  * non-task intent + empty plan → no raise
  * non-task intent + non-empty plan → no raise
  * task intent + empty plan → raises
  * task intent + non-empty plan → no raise
  * task intent + None plan → raises
  * contract is asserted at the top of the function
"""

from __future__ import annotations

import pytest

from core.runtime_engine.planner import (
    enforce_execution_obligation,
    detect_task_intent,
)
from core.runtime_engine.runtime_contracts import (
    ExecutionContract,
    ExecutionObligationViolation,
)


# ── Helpers ──────────────────────────────────────────────────────────


def _task_intent(intent_type: str = "analysis") -> object:
    """Build a TaskIntentResult with ``requires_execution=True``."""
    return detect_task_intent("分析数据")  # real detector, real shape


def _non_task_intent() -> object:
    """Build a TaskIntentResult with ``requires_execution=False``."""
    return detect_task_intent("hello")


# ── A: non-task intent + empty plan → no raise ──────────────────────


def test_non_task_intent_empty_plan_is_allowed():
    """A greeting / definition question with no tool requirement
    is allowed to return an empty plan — chitchat is exempt.
    """
    intent = _non_task_intent()
    assert intent.requires_execution is False
    enforce_execution_obligation(intent, [])  # must not raise


# ── B: non-task intent + non-empty plan → no raise ─────────────────


def test_non_task_intent_non_empty_plan_is_allowed():
    intent = _non_task_intent()
    fake_node = type("N", (), {})()  # any truthy non-empty list
    enforce_execution_obligation(intent, [fake_node])  # must not raise


# ── C: task intent + empty plan → raises ───────────────────────────


def test_task_intent_empty_plan_raises():
    """The core v4 contract: a task-intent request that returns
    no nodes is a planner failure. The function MUST raise.
    """
    intent = _task_intent()
    assert intent.requires_execution is True
    with pytest.raises(ExecutionObligationViolation) as excinfo:
        enforce_execution_obligation(intent, [])
    # The message names the intent_type for diagnostics.
    assert "intent_type" in str(excinfo.value)


# ── D: task intent + non-empty plan → no raise ─────────────────────


def test_task_intent_non_empty_plan_is_allowed():
    intent = _task_intent()
    fake_node = type("N", (), {})()
    enforce_execution_obligation(intent, [fake_node])  # must not raise


# ── E: task intent + None plan → raises ────────────────────────────


def test_task_intent_none_plan_raises():
    """Defensive: ``None`` is treated as an empty plan.
    The previous v3.10 planner would silently accept None and
    produce a TypeError downstream; the v4 guard catches the
    case explicitly.
    """
    intent = _task_intent()
    with pytest.raises(ExecutionObligationViolation):
        enforce_execution_obligation(intent, None)


# ── F: TaskIntentResult.requires_execution is the alias property ───


def test_task_intent_requires_execution_alias():
    """The v4 contract names the property ``requires_execution``;
    the existing ``requires_tool_likely`` is kept as a backward-
    compatible alias. The planner reads the new name.
    """
    intent = _task_intent()
    # Both properties exist and agree.
    assert hasattr(intent, "requires_execution")
    assert hasattr(intent, "requires_tool_likely")
    assert intent.requires_execution == intent.requires_tool_likely


# ── G: exception is a real Exception subclass ──────────────────────


def test_violation_is_exception():
    assert issubclass(ExecutionObligationViolation, Exception)
    # And it's a fresh class — not a stdlib error that might be
    # caught by accident.
    assert ExecutionObligationViolation.__module__ == "core.runtime_engine.runtime_contracts"


# ── H: contract assertion — EXECUTION_OBLIGATION_ENFORCED is on ────


def test_execution_obligation_contract_is_on():
    assert ExecutionContract.EXECUTION_OBLIGATION_ENFORCED is True


# ── I: planner.plan() end-to-end fail-fast on empty + task intent ──


def test_planner_plan_raises_for_empty_task_intent(monkeypatch):
    """End-to-end: ``Planner.plan()`` raises
    ``ExecutionObligationViolation`` when the LLM returns an
    empty plan for a task-intent request. We replace the LLM
    with a stub that returns ``{"nodes": []}`` and confirm the
    raise.
    """
    from core.runtime_engine.planner import Planner
    from core.runtime_engine.models import SSOTRuntimeConfig, StatelessContext
    import json

    def fake_llm(**_kw):
        return json.dumps({"nodes": []})

    cfg = SSOTRuntimeConfig()
    planner = Planner(
        config=cfg,
        available_tools={
            "test.tool": {
                "description": "",
                "args_schema": {"required": ["action"],
                                "properties": {"action": {"type": "string"}}},
            }
        },
        llm_invoke=fake_llm,
    )
    ctx = StatelessContext(
        workspace_id="default",
        session_id="audit_v4_planner_e2e",
        request_id="r-1",
        user_input="分析 OSPF 网络的 BGP 路由",
    )
    with pytest.raises(ExecutionObligationViolation):
        planner.plan(ctx)


def test_planner_plan_succeeds_for_empty_chitchat(monkeypatch):
    """End-to-end: empty plan for a chitchat question is allowed
    — the v4 fail-fast is obligation-driven, not blanket.
    """
    from core.runtime_engine.planner import Planner
    from core.runtime_engine.models import SSOTRuntimeConfig, StatelessContext
    import json

    def fake_llm(**_kw):
        return json.dumps({"nodes": []})

    cfg = SSOTRuntimeConfig()
    planner = Planner(
        config=cfg,
        available_tools={
            "test.tool": {
                "description": "",
                "args_schema": {"required": ["action"],
                                "properties": {"action": {"type": "string"}}},
            }
        },
        llm_invoke=fake_llm,
    )
    ctx = StatelessContext(
        workspace_id="default",
        session_id="audit_v4_planner_chitchat",
        request_id="r-2",
        user_input="你好",
    )
    # Must not raise.
    result = planner.plan(ctx)
    assert result == []