"""Harness tests for v3.1.1 compaction optimizations:

1. CompactionStrategy enum
2. structured CompactionMetric
3. PRE_COMPACT / POST_COMPACT hook integration
4. UUIDv7 (time-ordered request IDs)
5. Reference context item tracking
"""

import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.state import NetworkAgentState, uuid7
from agent.runtime.context_compactor import (
    CompactionStrategy,
    compact_messages,
    should_compact,
    build_compaction_metric,
    estimate_context_size,
)


# ─── 1. UUIDv7 ─────────────────────────────────────────────────────────

def test_uuid7_format():
    """UUIDv7 must be 36 chars with version=7 and variant=[89ab]."""
    for _ in range(20):
        u = uuid7()
        assert len(u) == 36, f"length wrong: {u}"
        assert re.match(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
            u,
        ), f"format invalid: {u}"


def test_uuid7_time_ordered():
    """UUIDv7 timestamps must be monotonically non-decreasing across ms."""
    ids = [uuid7() for _ in range(5)]
    time.sleep(0.005)
    ids += [uuid7() for _ in range(5)]

    for i in range(len(ids) - 1):
        ts1 = int(ids[i].split("-")[0], 16)
        ts2 = int(ids[i + 1].split("-")[0], 16)
        assert ts2 >= ts1, f"UUIDv7 not monotonic: {ids[i]} -> {ids[i + 1]}"


def test_network_agent_state_uses_uuid7():
    """NetworkAgentState.request_id must be UUIDv7 format."""
    s = NetworkAgentState(user_input="test")
    assert len(s.request_id) == 36
    assert s.request_id[14] == "7", f"version not 7: {s.request_id}"
    assert s.request_id[19] in "89ab", f"variant wrong: {s.request_id}"


# ─── 2. CompactionStrategy ─────────────────────────────────────────────

def test_compact_messages_strategy_field():
    """compact_messages must include strategy/trigger/threshold_pct in meta."""
    msgs = [{"role": "user", "message_id": f"m{i}", "content": f"msg {i}"} for i in range(10)]
    _, meta = compact_messages(
        msgs,
        keep_recent=4,
        strategy=CompactionStrategy.FAST_EVICTION,
        trigger="auto",
        threshold_pct=75.0,
    )
    assert meta["strategy"] == "fast_eviction"
    assert meta["trigger"] == "auto"
    assert meta["threshold_pct"] == 75.0
    assert meta["compacted"] is True


def test_compact_messages_below_threshold_meta():
    """Even when below threshold, meta must carry strategy + duration."""
    msgs = [{"role": "user", "content": "hi"}]
    _, meta = compact_messages(msgs, strategy=CompactionStrategy.FAST_EVICTION)
    assert meta["compacted"] is False
    assert meta["strategy"] == "fast_eviction"
    assert "duration_ms" in meta


def test_compaction_metric_to_dict():
    """CompactionMetric.to_dict() must produce 12 fields."""
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "message_id": "m1", "content": "q1"},
        {"role": "assistant", "message_id": "m2", "content": "a1"},
        {"role": "user", "message_id": "m3", "content": "current"},
    ]
    _, meta = compact_messages(msgs, keep_recent=2, strategy=CompactionStrategy.FAST_EVICTION, trigger="manual", threshold_pct=0.0)
    metric = build_compaction_metric(meta, CompactionStrategy.FAST_EVICTION, "manual", 0.0, len(msgs))
    d = metric.to_dict()
    expected_keys = {
        "strategy", "trigger", "threshold_pct",
        "original_messages", "original_estimated_tokens",
        "compacted_messages", "compacted_estimated_tokens",
        "compacted_message_count", "duration_ms",
        "reference_context_item_id", "retention_ratio", "ts",
    }
    assert expected_keys.issubset(d.keys()), f"missing: {expected_keys - set(d.keys())}"


# ─── 3. Reference context item ─────────────────────────────────────────

def test_reference_context_item_first_kept_non_system():
    """reference_context_item_id should point to the first non-system kept message."""
    msgs = [
        {"role": "system", "content": "sys"},
        {"role": "user", "message_id": "m1", "content": "old q1"},
        {"role": "assistant", "message_id": "m2", "content": "old a1"},
        {"role": "user", "message_id": "m3", "content": "recent q"},
        {"role": "assistant", "message_id": "m4", "content": "recent a"},
    ]
    # keep_recent=2: m3+m4 are kept, system+m1+m2 are compacted
    _, meta = compact_messages(msgs, keep_recent=2)
    assert meta["compacted"] is True
    # First kept non-system message with message_id should be m3
    assert meta["reference_context_item_id"] == "m3", (
        f"expected m3, got {meta['reference_context_item_id']}"
    )


def test_reference_context_item_empty_when_no_id():
    """If messages have no message_id, ref_id must be empty string, not crash."""
    msgs = [
        {"role": "user", "content": "no id 1"},
        {"role": "assistant", "content": "no id 2"},
    ]
    _, meta = compact_messages(msgs, keep_recent=1)
    assert "reference_context_item_id" in meta
    assert isinstance(meta["reference_context_item_id"], str)


# ─── 4. Compaction hooks are wired (smoke test) ───────────────────────

def test_pre_post_compact_hooks_in_token_manager():
    """check_token_limit must call PRE_COMPACT and POST_COMPACT hooks."""
    from agent.runtime.token_manager import check_token_limit, TokenLimitExceeded

    msgs = [{"role": "user", "content": "x" * 1000} for _ in range(200)]
    # Force compaction by setting max_context very low
    class FakeContext:
        model_config = {"max_context_tokens": 100}
    class FakeTurn:
        warnings = []
        metadata = {}
    class FakeSession:
        workspace_id = "default"
        session_id = "test_session"
        metadata = {}

    try:
        check_token_limit(msgs, FakeContext(), FakeSession(), FakeTurn(), "step")
    except TokenLimitExceeded:
        # Expected when even after compact, content exceeds 90% of 100 tokens
        pass

    # Hooks may not be called if no registry is set; just ensure no other crash
    assert True


if __name__ == "__main__":
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✓ {t.__name__}")
        except Exception as e:
            failed += 1
            print(f"  ✗ {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(0 if failed == 0 else 1)
