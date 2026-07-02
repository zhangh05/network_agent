"""
v4 Runtime Contracts — system-level invariant tests.

The v4 contract package is ``speg_engine.runtime_contracts`` and
exposes:

  * ``ExecutionContract`` — class with three boolean class
    attributes that the engine asserts at the top of every turn.
  * ``ExecutionObligationViolation`` — exception raised by the
    planner when the obligation is violated.

These tests assert:

  * All three contract flags are True by default.
  * The exception is importable and is an ``Exception`` subclass.
  * The engine's top-of-turn ``assert`` actually fires (i.e. the
    contract is wired in, not dead code).
  * Flipping a contract off causes the engine to refuse to run
    (the contract is enforced, not just declared).
  * The contract surface is stable: future refactors cannot
    silently remove a flag without breaking these tests.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from speg_engine.runtime_contracts import (
    ExecutionContract,
    ExecutionObligationViolation,
)


# ── A: contract flags are on by default ─────────────────────────────


def test_tool_truth_single_source_is_on():
    assert ExecutionContract.TOOL_TRUTH_SINGLE_SOURCE is True


def test_context_event_stream_only_is_on():
    assert ExecutionContract.CONTEXT_EVENT_STREAM_ONLY is True


def test_execution_obligation_enforced_is_on():
    assert ExecutionContract.EXECUTION_OBLIGATION_ENFORCED is True


# ── B: contract is class-level, not instance-level ─────────────────


def test_contract_flags_are_class_level():
    """The contract flags are CLASS-level attributes, not
    instance-level. Two separate reads of the class attribute
    must agree. Flipping a flag is a deliberate "contract OFF"
    operation visible to every consumer of the class.
    """
    assert "TOOL_TRUTH_SINGLE_SOURCE" in vars(ExecutionContract)
    assert "CONTEXT_EVENT_STREAM_ONLY" in vars(ExecutionContract)
    assert "EXECUTION_OBLIGATION_ENFORCED" in vars(ExecutionContract)


# ── C: ExecutionObligationViolation is an Exception ────────────────


def test_violation_is_an_exception():
    assert issubclass(ExecutionObligationViolation, Exception)
    # It must be raisable with a message and the message must
    # be readable on the resulting object.
    exc = ExecutionObligationViolation("test message")
    assert str(exc) == "test message"


def test_violation_can_be_raised_and_caught():
    with pytest.raises(ExecutionObligationViolation):
        raise ExecutionObligationViolation("violation")


# ── D: engine.run() asserts the three contracts at the top ────────


def test_engine_run_asserts_contracts(monkeypatch):
    """The engine MUST fail when a critical contract is turned off.

    v4.2: uses ContractValidator instead of raw assert; still
    returns a failure result with CONTRACT_VIOLATION error.
    """
    from speg_engine.engine import SPEGEngine
    from speg_engine.models import SPEGConfig

    cfg = SPEGConfig(enable_finalizer=False)

    def fake_llm(**_kw):
        return json.dumps({"nodes": []})

    registry = {}
    engine = SPEGEngine(
        config=cfg,
        llm_invoke=fake_llm,
        tool_registry=registry,
    )

    original = ExecutionContract.TOOL_TRUTH_SINGLE_SOURCE
    ExecutionContract.TOOL_TRUTH_SINGLE_SOURCE = False
    try:
        result = asyncio.run(engine.run("test", workspace_id="default",
                                        session_id="audit_v4_assert"))
        assert result.success is False, \
            f"Expected failure when TOOL_TRUTH_SINGLE_SOURCE is off, got: {result.metadata}"
        assert result.errors, "Expected at least one error"
        error_texts = [str(e) for e in result.errors]
        assert any("TOOL_TRUTH" in t for t in error_texts), \
            f"Error should reference TOOL_TRUTH_SINGLE_SOURCE: {error_texts}"
    finally:
        ExecutionContract.TOOL_TRUTH_SINGLE_SOURCE = original


def test_engine_run_asserts_context_contract(monkeypatch):
    """Same as above, but for the context-event-stream contract.
    v4.2: returns failure result via ContractValidator.
    """
    from speg_engine.engine import SPEGEngine
    from speg_engine.models import SPEGConfig

    cfg = SPEGConfig(enable_finalizer=False)

    def fake_llm(**_kw):
        return json.dumps({"nodes": []})

    registry = {}
    engine = SPEGEngine(
        config=cfg,
        llm_invoke=fake_llm,
        tool_registry=registry,
    )

    original = ExecutionContract.CONTEXT_EVENT_STREAM_ONLY
    ExecutionContract.CONTEXT_EVENT_STREAM_ONLY = False
    try:
        result = asyncio.run(engine.run("test", workspace_id="default",
                                        session_id="audit_v4_assert_ctx"))
        assert result.success is False
        assert result.errors
        error_texts = [str(e) for e in result.errors]
        assert any("CONTEXT_EVENT" in t for t in error_texts)
    finally:
        ExecutionContract.CONTEXT_EVENT_STREAM_ONLY = original


def test_engine_run_asserts_execution_obligation_contract(monkeypatch):
    """Same as above, but for the execution-obligation contract.
    v4.2: returns failure result via ContractValidator.
    """
    from speg_engine.engine import SPEGEngine
    from speg_engine.models import SPEGConfig

    cfg = SPEGConfig(enable_finalizer=False)

    def fake_llm(**_kw):
        return json.dumps({"nodes": []})

    registry = {}
    engine = SPEGEngine(
        config=cfg,
        llm_invoke=fake_llm,
        tool_registry=registry,
    )

    original = ExecutionContract.EXECUTION_OBLIGATION_ENFORCED
    ExecutionContract.EXECUTION_OBLIGATION_ENFORCED = False
    try:
        result = asyncio.run(engine.run("test", workspace_id="default",
                                        session_id="audit_v4_assert_eo"))
        assert result.success is False
        assert result.errors
        error_texts = [str(e) for e in result.errors]
        assert any("EXECUTION_OBLIGATION" in t for t in error_texts)
    finally:
        ExecutionContract.EXECUTION_OBLIGATION_ENFORCED = original


# ── E: tool_runtime._normalize_result also asserts the contract ────


def test_normalize_result_refuses_when_contract_off():
    """The single source of truth for tool success is
    ``_normalize_result`` — it also asserts the contract at
    its entry, so flipping the flag off blocks handler-result
    normalisation as well.
    """
    from speg_engine.tool_runtime import _normalize_result
    from speg_engine.models import ExecutionNode

    node = ExecutionNode(id="n1", tool="t", args={}, deps=[])
    original = ExecutionContract.TOOL_TRUTH_SINGLE_SOURCE
    ExecutionContract.TOOL_TRUTH_SINGLE_SOURCE = False
    try:
        with pytest.raises(AssertionError):
            _normalize_result(node, {"ok": True}, 0.0)
    finally:
        ExecutionContract.TOOL_TRUTH_SINGLE_SOURCE = original


# ── F: enforce_execution_obligation also asserts the contract ─────


def test_enforce_refuses_when_contract_off():
    """The planner's fail-fast guard also asserts the contract
    at its entry — flipping the flag off makes the function
    ABORT, not become a no-op. This is the symmetric contract:
    every enforcement point is loud, no silent fallback.
    """
    from speg_engine.planner import enforce_execution_obligation, detect_task_intent

    # Build a real task-intent through the detector.
    intent = detect_task_intent("分析数据")
    assert intent.requires_execution is True
    original = ExecutionContract.EXECUTION_OBLIGATION_ENFORCED
    ExecutionContract.EXECUTION_OBLIGATION_ENFORCED = False
    try:
        # The function asserts the contract at its top — with
        # the contract off, it raises AssertionError, not
        # silently no-ops.
        with pytest.raises(AssertionError) as excinfo:
            enforce_execution_obligation(intent, [])
        assert "EXECUTION_OBLIGATION_ENFORCED" in str(excinfo.value)
    finally:
        ExecutionContract.EXECUTION_OBLIGATION_ENFORCED = original


# ── G: all three modules import the contract from the same path ───


def test_contract_has_a_single_source_path():
    """All three consumer modules (tool_runtime, planner,
    engine, speg_adapter) import the contract from
    ``speg_engine.runtime_contracts``. This is the meta-
    guarantee that the contract is not silently redefined
    elsewhere.
    """
    import speg_engine.runtime_contracts as rc
    assert hasattr(rc, "ExecutionContract")
    assert hasattr(rc, "ExecutionObligationViolation")
    # No re-export from a different path: the contract is
    # defined exactly once.
    import speg_engine.tool_runtime as tr
    assert tr.ExecutionContract is rc.ExecutionContract
    import speg_engine.planner as pl
    assert pl.ExecutionContract is rc.ExecutionContract
    import speg_engine.engine as en
    assert en.ExecutionContract is rc.ExecutionContract
    import agent.runtime.speg_adapter as sa
    assert sa.ExecutionContract is rc.ExecutionContract