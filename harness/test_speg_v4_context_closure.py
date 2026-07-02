"""
v4 Context Closure — single-source event stream tests.

The v4 contract ``ExecutionContract.CONTEXT_EVENT_STREAM_ONLY`` mandates
that conversation history flows through exactly one builder —
``agent.runtime.speg_adapter.build_context_events`` — which:

  1. Reads in-memory ``session.history`` (objects with role/content).
  2. Reads on-disk ``SessionMessageStore.get_messages()`` (dicts with
     role/content/created_at).
  3. Normalises both into a uniform ``{role, content, created_at}``
     shape.
  4. Sorts by ``created_at`` chronologically.
  5. Deduplicates by ``(role, content[:80])``.

No other code path may read either source directly for context
injection. The previous dual-merge in ``_populate_from_session``
is now centralised in this builder.

These tests exercise the builder's behaviour without a real
``SessionMessageStore`` (the store is a thin wrapper around
``messages.jsonl``; we patch the import to return a controlled
sequence of dicts).
"""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace

import pytest

from speg_engine.runtime_contracts import ExecutionContract


def _import_builder():
    """Import the builder. We use a fresh import per test so the
    module's lazy imports are re-evaluated cleanly."""
    from agent.runtime.speg_adapter import build_context_events
    return build_context_events


def _fake_session(history=None, *, workspace_id="default",
                  session_id="audit_v4") -> SimpleNamespace:
    """Build a mock session with arbitrary in-memory history."""
    s = SimpleNamespace()
    s.workspace_id = workspace_id
    s.session_id = session_id
    s.history = history or []
    return s


def _msg(role: str, content: str) -> SimpleNamespace:
    """Build an in-memory message object (matches the shape of
    the real ``Session.history`` entries)."""
    return SimpleNamespace(role=role, content=content)


# ── A: empty session returns empty list ──────────────────────────────


def test_empty_session_returns_empty_list():
    build_context_events = _import_builder()
    out = build_context_events(_fake_session())
    assert out == []


# ── B: session with no session_id returns in-memory events only ────


def test_session_without_id_returns_memory_only(monkeypatch):
    """Without a ``session_id`` the builder cannot construct a
    ``SessionMessageStore`` (it would raise). The builder must
    still return the in-memory events gracefully — the disk
    read is a best-effort layer, not a hard dependency.
    """
    build_context_events = _import_builder()
    s = _fake_session(
        history=[_msg("user", "hello"), _msg("assistant", "hi")],
        session_id="",  # no session_id → skip disk
    )
    out = build_context_events(s)
    assert len(out) == 2
    assert out[0]["role"] == "user"
    assert out[0]["content"] == "hello"
    assert out[1]["role"] == "assistant"
    assert out[1]["content"] == "hi"
    # Both events carry a created_at — in-memory events use
    # the millis-offset base the builder assigns.
    assert all("created_at" in e for e in out)


# ── C: disk read merges with in-memory, sorted by created_at ────────


def test_disk_and_memory_are_merged_and_sorted(monkeypatch):
    """A controlled disk return (3 events with explicit
    timestamps) must interleave correctly with the in-memory
    history (2 events) — final output is sorted by created_at
    and deduplicated.
    """
    build_context_events = _import_builder()

    disk_payload = [
        {"role": "user", "content": "first turn", "created_at": "1000"},
        {"role": "assistant", "content": "first reply", "created_at": "1010"},
        {"role": "user", "content": "second turn", "created_at": "1020"},
    ]
    # Patch SessionMessageStore at import time.
    fake_store_mod = types.ModuleType("workspace.message_store")

    class FakeStore:
        def __init__(self, session_id, ws_id):
            pass

        def get_messages(self):
            return list(disk_payload)

    fake_store_mod.SessionMessageStore = FakeStore
    monkeypatch.setitem(sys.modules, "workspace.message_store", fake_store_mod)
    # Also register the parent package so the relative import inside
    # the builder resolves.
    if "workspace" not in sys.modules:
        sys.modules["workspace"] = types.ModuleType("workspace")
    sys.modules["workspace"].message_store = fake_store_mod

    s = _fake_session(
        history=[
            _msg("user", "third turn"),
            _msg("assistant", "third reply"),
        ],
        session_id="audit_v4_disk_merge",
    )
    out = build_context_events(s)
    roles = [e["role"] for e in out]
    contents = [e["content"] for e in out]

    # All 5 events present (3 disk + 2 memory), no duplicates.
    assert len(out) == 5
    assert "first turn" in contents
    assert "third reply" in contents

    # Disk events come first by created_at; memory events (whose
    # millis-offset base is later) come last.
    disk_contents = {"first turn", "first reply", "second turn"}
    assert {out[0]["content"], out[1]["content"], out[2]["content"]} == disk_contents
    assert out[3]["content"] == "third turn"
    assert out[4]["content"] == "third reply"


# ── D: deduplication by (role, content[:80]) ────────────────────────


def test_dedup_by_role_and_content_prefix(monkeypatch):
    """The same message appearing in both disk and memory must
    only appear once in the output.
    """
    build_context_events = _import_builder()

    disk_payload = [
        {"role": "user", "content": "shared question", "created_at": "1000"},
        {"role": "assistant", "content": "shared answer", "created_at": "1010"},
    ]
    fake_store_mod = types.ModuleType("workspace.message_store")

    class FakeStore:
        def __init__(self, session_id, ws_id):
            pass

        def get_messages(self):
            return list(disk_payload)

    fake_store_mod.SessionMessageStore = FakeStore
    monkeypatch.setitem(sys.modules, "workspace.message_store", fake_store_mod)
    if "workspace" not in sys.modules:
        sys.modules["workspace"] = types.ModuleType("workspace")
    sys.modules["workspace"].message_store = fake_store_mod

    s = _fake_session(
        history=[
            _msg("user", "shared question"),  # duplicate of disk
            _msg("assistant", "shared answer"),  # duplicate of disk
        ],
        session_id="audit_v4_dedup",
    )
    out = build_context_events(s)
    contents = [e["content"] for e in out]
    # No duplicates.
    assert len(contents) == len(set(contents))
    assert contents.count("shared question") == 1
    assert contents.count("shared answer") == 1


# ── E: disk read failure is contained ──────────────────────────────


def test_disk_read_failure_returns_memory_only(monkeypatch):
    """If ``SessionMessageStore.get_messages()`` raises, the
    builder must catch the exception and return the in-memory
    events. The previous v3.10 silent fallback is now
    centralised in the builder — there is no other code path
    that touches the disk store.
    """
    build_context_events = _import_builder()

    fake_store_mod = types.ModuleType("workspace.message_store")

    class BrokenStore:
        def __init__(self, session_id, ws_id):
            pass

        def get_messages(self):
            raise IOError("simulated disk failure")

    fake_store_mod.SessionMessageStore = BrokenStore
    monkeypatch.setitem(sys.modules, "workspace.message_store", fake_store_mod)
    if "workspace" not in sys.modules:
        sys.modules["workspace"] = types.ModuleType("workspace")
    sys.modules["workspace"].message_store = fake_store_mod

    s = _fake_session(
        history=[_msg("user", "memory-only")],
        session_id="audit_v4_disk_fail",
    )
    out = build_context_events(s)
    # Memory events survive the disk failure.
    assert len(out) == 1
    assert out[0]["content"] == "memory-only"


# ── F: only user / assistant roles pass through ─────────────────────


def test_only_user_and_assistant_roles_pass():
    """System / tool / other role entries are filtered out —
    only the user/assistant conversation thread is part of the
    event stream.
    """
    build_context_events = _import_builder()
    s = _fake_session(
        history=[
            _msg("user", "hi"),
            _msg("system", "system prompt"),
            _msg("assistant", "hello"),
            _msg("tool", "tool output"),
        ],
        session_id="",  # skip disk
    )
    out = build_context_events(s)
    roles = [e["role"] for e in out]
    assert roles == ["user", "assistant"]


# ── G: empty-content messages are filtered out ─────────────────────


def test_empty_content_messages_are_filtered():
    build_context_events = _import_builder()
    s = _fake_session(
        history=[
            _msg("user", ""),  # empty
            _msg("user", "   "),  # whitespace
            _msg("user", "real"),
        ],
        session_id="",
    )
    out = build_context_events(s)
    assert len(out) == 1
    assert out[0]["content"] == "real"


# ── H: contract assertion — CONTEXT_EVENT_STREAM_ONLY is on ────────


def test_context_event_contract_is_on():
    assert ExecutionContract.CONTEXT_EVENT_STREAM_ONLY is True