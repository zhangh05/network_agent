"""v3.9.8 contract: type consistency for timestamps and durations.

Earlier versions split the same field name across two representations:
  - ``created_at`` / ``started_at`` / ``finished_at``: some dataclasses
    used ``float`` (Unix epoch), others ``str`` (ISO-8601).
  - ``duration_ms``: some dataclasses used ``float`` (sub-ms precision),
    others ``int`` (canonical ToolResult shape).
  - ``timeout``: some signatures annotated ``float``, others ``int``.

API consumers (especially the workbench frontend) had to branch on
type per field. v3.9.8 unifies them:
  - all timestamp fields: ``str`` (ISO-8601 UTC)
  - all duration_ms fields: ``int``
  - all timeout parameters: ``int`` (seconds)

These tests pin the consistency so future regressions are caught.
"""

import inspect
from datetime import datetime, timezone

from agent.runtime.utils import to_iso, from_iso, now_iso, duration_ms


# ── Timestamp fields ───────────────────────────────────────────────────


def test_approval_request_created_at_is_iso_str():
    """ApprovalRequest.created_at is an ISO-8601 str (was float)."""
    from agent.approval import ApprovalRequest

    r = ApprovalRequest(
        approval_id="a1", session_id="s1", tool_id="exec.run",
        arguments={"command": "ls"}, description="test", risk_level="high",
    )
    assert isinstance(r.created_at, str), (
        f"ApprovalRequest.created_at must be str, got {type(r.created_at).__name__}"
    )
    # ISO-8601 parses successfully
    parsed = datetime.fromisoformat(r.created_at)
    assert parsed.tzinfo is not None


def test_approval_request_resolved_at_is_iso_str_or_none():
    from agent.approval import ApprovalRequest

    r = ApprovalRequest(
        approval_id="a1", session_id="s1", tool_id="exec.run",
        arguments={}, description="test", risk_level="high",
    )
    assert r.resolved_at is None or isinstance(r.resolved_at, str)


def test_action_result_timestamp_fields_are_str():
    """ActionResult.started_at / finished_at are ISO-8601 str."""
    from agent.runtime.actions.models import ActionResult

    ar = ActionResult()
    # Defaults are empty strings; setting through dispatcher path is tested below.
    assert isinstance(ar.started_at, str)
    assert isinstance(ar.finished_at, str)


def test_tool_dispatcher_writes_iso_strings():
    """ToolDispatcher populates started_at / finished_at as ISO and
    latency_ms as int milliseconds."""
    from agent.runtime.actions.dispatcher import ToolDispatcher
    from agent.runtime.actions.models import ActionPlan
    from types import SimpleNamespace

    plan = ActionPlan(
        action_id="a1", tool_call_id="tc1",
        tool_name="exec.run", tool_id="exec.run",
        arguments={"command": "ls"},
    )
    # Build a minimal ctx with a tool_router.
    class FakeRouter:
        def dispatch(self, tool_call, ctx):
            return SimpleNamespace(ok=True)

    class FakeCtx:
        tool_router = FakeRouter()

    d = ToolDispatcher().dispatch(plan, SimpleNamespace(), ctx=FakeCtx())
    assert isinstance(d.started_at, str)
    assert isinstance(d.finished_at, str)
    assert isinstance(d.latency_ms, int)
    # duration_ms >= 0
    assert d.latency_ms >= 0


def test_runtime_step_duration_ms_is_int_or_none():
    from agent.runtime.durable.models import RuntimeStep

    rs = RuntimeStep(step_id="s1", task_id="t1")
    assert rs.duration_ms is None or isinstance(rs.duration_ms, int)


def test_trajectory_record_duration_ms_is_int():
    from agent.runtime.durable.trajectory import TrajectoryRecord, TrajectoryMetrics

    tr = TrajectoryRecord()
    assert isinstance(tr.duration_ms, int)
    tm = TrajectoryMetrics()
    assert isinstance(tm.duration_ms, int)


# ── Timeout signatures ────────────────────────────────────────────────


def test_subscribe_timeout_is_int():
    sig = inspect.signature(__import__(
        "agent.runtime.session_events",
        fromlist=["subscribe"],
    ).subscribe)
    p = sig.parameters["timeout"]
    # annotation may be the ``int`` builtin or the string "int" depending on
    # how the source was authored. Both are valid markers of an int parameter.
    assert p.annotation in (int, "int"), (
        f"subscribe.timeout annotation must be int, got {p.annotation!r}"
    )


def test_approval_store_wait_timeout_is_int():
    sig = inspect.signature(__import__(
        "agent.approval", fromlist=["ApprovalStore"]
    ).ApprovalStore.wait)
    p = sig.parameters["timeout"]
    assert p.annotation in (int, "int"), (
        f"ApprovalStore.wait.timeout annotation must be int, got {p.annotation!r}"
    )


def test_device_session_recv_timeout_is_int():
    sig = inspect.signature(__import__(
        "agent.modules.remote.core", fromlist=["DeviceSession"]
    ).DeviceSession.recv)
    p = sig.parameters["timeout"]
    assert p.annotation in (int, "int"), (
        f"DeviceSession.recv.timeout annotation must be int, got {p.annotation!r}"
    )


# ── duration_ms signatures ─────────────────────────────────────────────


def test_tool_result_duration_ms_is_int():
    from core.tools.schemas import ToolResult
    fields = ToolResult.__dataclass_fields__
    assert "duration_ms" in fields
    t = fields["duration_ms"].type
    assert t in (int, "int"), (
        f"ToolResult.duration_ms must be int, got {t!r}"
    )


def test_compaction_metric_duration_ms_is_int():
    """CompactionMetric uses ``__slots__`` (not @dataclass). We assert
    that the runtime constructor's ``duration_ms`` parameter is
    annotated as ``int``.
    """
    from agent.runtime.context_compactor import CompactionMetric
    sig = inspect.signature(CompactionMetric.__init__)
    p = sig.parameters["duration_ms"]
    assert p.annotation in (int, "int"), (
        f"CompactionMetric.__init__.duration_ms must be int, got {p.annotation!r}"
    )


def test_internal_time_utils_helpers_round_trip():
    """to_iso / from_iso / duration_ms are inverse-consistent."""
    now = now_iso()
    assert isinstance(now, str)
    # Parses back
    epoch = from_iso(now)
    assert isinstance(epoch, float)
    # Re-encode yields same string (modulo microsecond precision).
    back = to_iso(epoch)
    assert datetime.fromisoformat(back) == datetime.fromisoformat(now)

    # duration_ms between two known ISO strings
    a = "2024-06-29T10:00:00.000000+00:00"
    b = "2024-06-29T10:00:01.500000+00:00"
    assert duration_ms(a, b) == 1500
    assert isinstance(duration_ms(a, b), int)


def test_to_iso_accepts_epoch_input_for_internal_runtime_math():
    """to_iso can encode an epoch value produced by internal runtime timers."""
    out = to_iso(1751188800.0)
    assert isinstance(out, str)
    # Round-trip
    assert abs(from_iso(out) - 1751188800.0) < 0.001


def test_from_iso_rejects_naive_timestamps():
    import pytest

    with pytest.raises(ValueError):
        from_iso("2026-06-30T10:00:00")


def test_observability_event_timestamp_is_timezone_aware_iso():
    from observability.schemas import TraceEvent

    event = TraceEvent(event_type="agent_start")
    parsed = datetime.fromisoformat(event.timestamp)
    assert parsed.tzinfo is not None


def test_context_bundle_timestamp_is_timezone_aware_iso():
    from core.context.schemas import ContextBundle

    bundle = ContextBundle()
    parsed = datetime.fromisoformat(bundle.created_at)
    assert parsed.tzinfo is not None
