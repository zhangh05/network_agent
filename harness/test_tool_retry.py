"""
Tool retry / execution-repair closed-loop tests for SSOT Runtime.

These tests exercise the v3.10 retry pipeline end-to-end. They:

  * build a fake ``Engine`` run with a mock tool that either
    succeeds on the retry, fails twice, or refuses to retry,
  * drive the run via ``SSOTRuntimeEngine.run()`` (the public entry
    point), and
  * assert the policy-decision outcomes, the metadata /
    audit / trace events, and the DAG dependency gate.

All tool handlers live in this file — no backend / network / LLM
calls. The LLM is replaced by a ``mock_llm`` that returns a JSON
plan with the user-specified nodes.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest


# ── Helper builders ────────────────────────────────────────────────────

def _make_engine(plan_nodes: list[dict], tool_handler, *, tool_id: str,
                 config_overrides: dict | None = None):
    """Build a SSOTRuntimeEngine that plans ``plan_nodes`` and dispatches
    ``tool_id`` to ``tool_handler``. Returns the engine."""
    from core.runtime_engine.engine import SSOTRuntimeEngine
    from core.runtime_engine.models import SSOTRuntimeConfig

    plan = {"nodes": plan_nodes}

    def mock_llm(**_kw):
        return json.dumps(plan)

    registry = {tool_id: {"description": "", "args_schema": {
        "required": ["action"],
        "properties": {"action": {"type": "string"}},
    }}}
    cfg_kwargs = {"enable_finalizer": False}
    if config_overrides:
        cfg_kwargs.update(config_overrides)
    cfg = SSOTRuntimeConfig(**cfg_kwargs)
    engine = SSOTRuntimeEngine(
        config=cfg, llm_invoke=mock_llm, tool_registry=registry,
    )
    engine.register_tool(tool_id, tool_handler)
    return engine


def _run(engine) -> Any:
    return asyncio.run(engine.run("test"))


def _run_approved(engine) -> Any:
    """Run with pre-approved risk so exec.run / high-risk tools can execute."""
    return asyncio.run(engine.run("test", extras={"approved_risk": True}))


def _find_node(result, node_id: str):
    return result.node_results.get(node_id)


# ── Test 1: read-only tool, first call TOOL_TIMEOUT, second OK ───────

def test_read_only_timeout_first_call_recovers():
    """read-only / idempotent / max_retries=1 / first call raises
    a TOOL_TIMEOUT-class error, second call succeeds.
    """
    from core.runtime_engine.contracts import get_contract

    # Confirm the contract surface for knowledge.manage.
    c = get_contract("knowledge.manage")
    assert c.idempotent is True
    assert c.side_effect == "read"
    assert c.max_retries == 1

    call_count = [0]

    async def handler(args):
        call_count[0] += 1
        if call_count[0] == 1:
            raise RuntimeError("connection reset by peer")
        return "ok"

    engine = _make_engine(
        plan_nodes=[{"id": "n1", "tool": "knowledge.manage",
                     "args": {"action": "search", "query": "x"}, "deps": []}],
        tool_handler=handler, tool_id="knowledge.manage",
    )
    result = _run(engine)

    assert result.success, f"errors: {result.errors}"
    assert call_count[0] == 2, f"handler called {call_count[0]} times"
    node = _find_node(result, "n1")
    assert node.success is True
    assert node.retry_count == 1
    # Downstream node is allowed to run.
    rs = result.metadata.get("retry_summary", {})
    assert rs.get("retry_succeeded") == 1
    # Trace event surface.
    events = result.metadata.get("retry_events") or []
    assert any(e.get("final_status") == "succeeded" for e in events)


# ── Test 2: read-only tool, two consecutive failures ─────────────────

def test_read_only_two_consecutive_failures_skip_downstream():
    call_count = [0]

    async def handler(args):
        call_count[0] += 1
        raise RuntimeError("connection reset by peer")

    engine = _make_engine(
        plan_nodes=[
            {"id": "n1", "tool": "knowledge.manage",
             "args": {"action": "search"}, "deps": []},
            {"id": "n2", "tool": "knowledge.manage",
             "args": {"action": "search"}, "deps": ["n1"]},
        ],
        tool_handler=handler, tool_id="knowledge.manage",
    )
    result = _run(engine)

    assert call_count[0] == 2, f"handler called {call_count[0]} times"
    n1 = _find_node(result, "n1")
    n2 = _find_node(result, "n2")
    assert n1.success is False
    assert n1.retry_count == 1
    # Downstream must NOT have been invoked.
    assert n2.error_code == "DEPENDENCY_FAILED"
    assert n2.metadata.get("skip_reason") == "dependency_failed"
    # Engine must report the failed retry.
    rs = result.metadata.get("retry_summary", {})
    assert rs.get("retry_failed") == 1
    assert "n1" in rs.get("retried_nodes", [])


# ── Test 3: idempotent=False → no retry ───────────────────────────────

def test_non_idempotent_tool_does_not_retry():
    """workspace.file has idempotent=False; even with side_effect=read
    it must not retry. (We need a tool with side_effect=read +
    idempotent=False, so we use a synthetic contract via the policy
    unit-test instead of an engine.run — see test_retry_policy_table
    below for the unit-level coverage.)
    """
    from core.runtime_engine.tool_retry_policy import should_retry_tool_failure

    @pytest.fixture
    def _node():
        class N:
            retry_count = 0
        return N()

    @pytest.fixture
    def _contract():
        class C:
            idempotent = False
            side_effect = "read"
            max_retries = 1
        return C()

    # Inline the call so we don't need a fixture.
    class N:
        retry_count = 0
    class C:
        idempotent = False
        side_effect = "read"
        max_retries = 1
    d = should_retry_tool_failure(
        node=N(), tool_contract=C(),
        error_code="TOOL_TIMEOUT",
    )
    assert d.retry_allowed is False
    assert d.reason == "non_idempotent"
    assert d.blocked_by_policy is True


# ── Test 4: side_effect=write_file → no retry ─────────────────────────

def test_write_file_side_effect_does_not_retry():
    from core.runtime_engine.tool_retry_policy import should_retry_tool_failure

    class N:
        retry_count = 0
    class C:
        idempotent = True
        side_effect = "write_file"
        max_retries = 1
    d = should_retry_tool_failure(
        node=N(), tool_contract=C(), error_code="TOOL_TIMEOUT",
    )
    assert d.retry_allowed is False
    assert "side_effect_not_retryable" in d.reason
    assert d.blocked_by_policy is True


# ── Test 5: exec.run → no retry ───────────────────────────────────────

def test_exec_run_does_not_retry():
    from core.runtime_engine.contracts import get_contract
    from core.runtime_engine.tool_retry_policy import should_retry_tool_failure

    c = get_contract("exec.run")
    # Sanity — exec.run must keep its high-risk contract.
    assert c.side_effect == "execute_command"
    assert c.idempotent is False
    assert c.max_retries == 0

    call_count = [0]

    async def handler(args):
        call_count[0] += 1
        raise RuntimeError("kaboom")

    engine = _make_engine(
        plan_nodes=[{"id": "x", "tool": "exec.run",
                     "args": {"action": "shell", "command": "ls"},
                     "deps": []}],
        tool_handler=handler, tool_id="exec.run",
    )
    result = _run_approved(engine)

    # The handler is invoked exactly once — no retry.
    assert call_count[0] == 1
    rs = result.metadata.get("retry_summary", {})
    assert rs.get("retry_attempts") == 0
    events = result.metadata.get("retry_events") or []
    assert events
    assert events[0]["blocked_by_policy"] is True
    assert "execute_command_not_retryable" in events[0]["reason"] or \
           "non_idempotent" in events[0]["reason"] or \
           "zero_max_retries" in events[0]["reason"]


# ── Test 6: FORBIDDEN_COMMAND → no retry, no LLM replan ──────────────

def test_forbidden_command_does_not_retry():
    from core.runtime_engine.tool_retry_policy import should_retry_tool_failure

    class N:
        retry_count = 0
    class C:
        idempotent = True
        side_effect = "read"
        max_retries = 1
    d = should_retry_tool_failure(
        node=N(), tool_contract=C(), error_code="FORBIDDEN_COMMAND",
    )
    assert d.retry_allowed is False
    assert "FORBIDDEN_COMMAND" in d.reason
    assert d.blocked_by_policy is True


# ── Test 7: POLICY_BLOCKED → no retry ────────────────────────────────

def test_policy_blocked_does_not_retry():
    from core.runtime_engine.tool_retry_policy import should_retry_tool_failure

    class N:
        retry_count = 0
    class C:
        idempotent = True
        side_effect = "read"
        max_retries = 1
    d = should_retry_tool_failure(
        node=N(), tool_contract=C(), error_code="POLICY_BLOCKED",
    )
    assert d.retry_allowed is False
    assert "POLICY_BLOCKED" in d.reason
    assert d.blocked_by_policy is True


# ── Test 8: layer with 4 nodes, only failed node retried ─────────────

def test_layer_retries_only_failed_node():
    """4-node layer: A OK, B OK, C fails once then OK, D OK.
    The handler's call counter per node proves only C was re-run.
    """
    counts = {"A": 0, "B": 0, "C": 0, "D": 0}

    async def handler(args):
        # Each plan node carries ``q`` = its own id, so a single
        # handler can dispatch to the right counter.
        node_id = args.get("q", "")
        counts[node_id] += 1
        if node_id == "C" and counts[node_id] == 1:
            raise RuntimeError("connection reset")
        return f"ok-{node_id}"

    from core.runtime_engine.engine import SSOTRuntimeEngine
    from core.runtime_engine.models import SSOTRuntimeConfig

    plan = {
        "nodes": [
            {"id": "A", "tool": "knowledge.manage",
             "args": {"action": "search", "q": "A"}, "deps": []},
            {"id": "B", "tool": "knowledge.manage",
             "args": {"action": "search", "q": "B"}, "deps": []},
            {"id": "C", "tool": "knowledge.manage",
             "args": {"action": "search", "q": "C"}, "deps": []},
            {"id": "D", "tool": "knowledge.manage",
             "args": {"action": "search", "q": "D"}, "deps": []},
        ],
    }

    def mock_llm(**_):
        return json.dumps(plan)

    registry = {"knowledge.manage": {"description": "", "args_schema": {
        "required": ["action"],
        "properties": {"action": {"type": "string"},
                       "q": {"type": "string"}},
    }}}
    engine = SSOTRuntimeEngine(
        config=SSOTRuntimeConfig(enable_finalizer=False),
        llm_invoke=mock_llm, tool_registry=registry,
    )
    engine.register_tool("knowledge.manage", handler)
    result = asyncio.run(engine.run("test"))
    # A/B/D: 1 call each. C: 2 calls (1 fail + 1 retry success).
    assert counts == {"A": 1, "B": 1, "C": 2, "D": 1}, counts
    assert result.success
    rs = result.metadata.get("retry_summary", {})
    assert rs.get("retry_succeeded") == 1
    assert "C" in rs.get("retried_nodes", [])


# ── Test 9: effective_max_retries clamped to global cap ─────────────

def test_global_max_retries_clamp():
    """tool.max_retries=3 + global cap=1 → effective=1; only 1
    retry actually fires. Budget exhaustion also blocks.
    """
    from core.runtime_engine.tool_retry_policy import (
        should_retry_tool_failure, effective_max_retries,
    )

    class N:
        retry_count = 0
    class C:
        idempotent = True
        side_effect = "read"
        max_retries = 3
    d = should_retry_tool_failure(
        node=N(), tool_contract=C(), error_code="TOOL_TIMEOUT",
        global_max_retries_per_node=1,
    )
    assert d.retry_allowed is True
    assert d.max_retries == 1
    # Now the global cap is 0 → no retry.
    d2 = should_retry_tool_failure(
        node=N(), tool_contract=C(), error_code="TOOL_TIMEOUT",
        global_max_retries_per_node=0,
    )
    assert d2.retry_allowed is False
    # effective_max_retries helper returns the cap, clamped to 0
    # when global is 0.
    assert effective_max_retries(C(), global_max=1) == 1
    assert effective_max_retries(C(), global_max=0) == 0

    # Budget exhaustion blocks the retry at the engine level —
    # call the policy with budget_ok=False and confirm refusal.
    d3 = should_retry_tool_failure(
        node=N(), tool_contract=C(), error_code="TOOL_TIMEOUT",
        global_max_retries_per_node=1, budget_ok=False,
    )
    assert d3.retry_allowed is False
    assert d3.reason == "budget_exceeded"


# ── Test 10: redaction of sensitive fields in audit/trace payload ────

def test_retry_event_redacts_sensitive_fields():
    """The retry event must not leak API keys, tokens, passwords,
    secrets, or private command payloads. We craft a node whose
    error message embeds a fake credential and verify the
    serialized event does not surface it.
    """
    secret_token = "AKIA-SECRET-DO-NOT-LEAK-12345"
    call_count = [0]

    async def handler(args):
        call_count[0] += 1
        if call_count[0] == 1:
            # Pretend the upstream provider leaked our token in
            # the error string — a real scenario.
            raise RuntimeError(
                f"request failed; Authorization: Bearer {secret_token}"
            )
        return "ok"

    engine = _make_engine(
        plan_nodes=[{"id": "n1", "tool": "knowledge.manage",
                     "args": {"action": "search", "q": "x"}, "deps": []}],
        tool_handler=handler, tool_id="knowledge.manage",
    )
    result = _run(engine)
    assert result.success

    events = result.metadata.get("retry_events") or []
    assert events
    e = events[0]
    # Either the policy redactions stripped the token, OR the
    # 'original_error' truncation already removed it (we keep
    # the first 200 characters). Either way: the token must
    # not appear verbatim in the audit-shaped event.
    serialized = json.dumps(e, ensure_ascii=False, default=str)
    assert secret_token not in serialized, (
        f"secret leaked into retry event: {serialized!r}"
    )


# ── Test 11: retry_original_error in node result metadata must be redacted ────

def test_retry_metadata_retry_original_error_is_redacted():
    """``retry_result.metadata["retry_original_error"]`` must NOT contain
    raw credentials.  The value must come from
    ``decision.notes["original_error"]`` (already scrubbed by
    ``redact_sensitive_text``), not from ``original_result.error``.
    """
    secrets = (
        "Authorization: Bearer AKIAIOSFODNN7EXAMPLE",
        "api_key=sk-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "password=123456",
    )
    error_msg = "; ".join(secrets)
    call_count = [0]

    async def handler(args):
        call_count[0] += 1
        if call_count[0] == 1:
            raise RuntimeError(error_msg)
        return "ok"

    engine = _make_engine(
        plan_nodes=[{"id": "n1", "tool": "knowledge.manage",
                     "args": {"action": "search", "q": "x"}, "deps": []}],
        tool_handler=handler, tool_id="knowledge.manage",
    )
    result = _run(engine)
    assert result.success

    node_result = result.node_results.get("n1")
    assert node_result is not None, "n1 missing from results"

    raw = node_result.metadata.get("retry_original_error", "")

    # None of the raw secret substrings may appear.
    for secret in secrets:
        assert secret not in raw, (
            f"raw secret leaked into retry_original_error: {raw!r}"
        )

    # The redacted marker MUST appear at least once.
    assert "***REDACTED***" in raw, (
        f"retry_original_error not redacted: {raw!r}"
    )
