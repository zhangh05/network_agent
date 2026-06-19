"""Regression tests for v3.2.1 review fixes (round 3).

Covers:
- compact() atomicity (tmp + os.replace)
- include_deleted actually returning tombstones
- run_id path-traversal protection
- session_id validation now uses workspace.ids
- schema_registry includes trace_id/run_id/tags
- context_store timestamps are UTC ISO 8601
- workspace state.json atomic write
"""
import json
import os
import time
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Atomic compact()
# ---------------------------------------------------------------------------

def test_compact_is_atomic_when_write_fails(monkeypatch, tmp_path):
    """If writing the rewritten JSONL fails, the original file must survive."""
    from context import context_store as cs

    monkeypatch.setattr(cs, "_ws_root", lambda ws="default": tmp_path / ws / "context")
    store = cs.ContextStore("default")

    # Seed two items so compact has something to rewrite
    store.put({"item_type": "memory_hit", "content": "a"})
    store.put({"item_type": "memory_hit", "content": "b"})
    store.delete(store.put({"item_type": "memory_hit", "content": "c"}))

    original = (tmp_path / "default" / "context" / "items.jsonl").read_text()
    original_lines = original.strip().split("\n")
    assert len(original_lines) == 4  # 2 puts + 1 delete + 1 implicit

    # Force os.open to fail when writing the .tmp path
    import contextlib
    real_os_open = cs.os.open
    def boom(path, *args, **kwargs):
        if str(path).endswith(".tmp"):
            raise OSError("simulated disk full")
        return real_os_open(path, *args, **kwargs)
    monkeypatch.setattr(cs.os, "open", boom)

    with pytest.raises(OSError):
        store.compact()

    # Original file untouched
    after = (tmp_path / "default" / "context" / "items.jsonl").read_text()
    assert after == original, "original items.jsonl must survive a failed compact"

    # No leftover .tmp file
    assert not (tmp_path / "default" / "context" / "items.jsonl.tmp").exists()


def test_compact_succeeds_and_drops_tombstones(monkeypatch, tmp_path):
    from context import context_store as cs

    monkeypatch.setattr(cs, "_ws_root", lambda ws="default": tmp_path / ws / "context")
    store = cs.ContextStore("default")
    live_id = store.put({"item_type": "memory_hit", "content": "keep"})
    dead_id = store.put({"item_type": "memory_hit", "content": "drop"})
    store.delete(dead_id)

    summary = store.compact()
    assert summary["after"] == 1
    assert summary["removed"] == 1

    items = (tmp_path / "default" / "context" / "items.jsonl").read_text().strip().split("\n")
    assert len(items) == 1
    assert json.loads(items[0])["item_id"] == live_id


# ---------------------------------------------------------------------------
# include_deleted
# ---------------------------------------------------------------------------

def test_include_deleted_returns_tombstones(monkeypatch, tmp_path):
    from context import context_store as cs

    monkeypatch.setattr(cs, "_ws_root", lambda ws="default": tmp_path / ws / "context")
    store = cs.ContextStore("default")
    store.put({"item_type": "memory_hit", "content": "live"})
    dead_id = store.put({"item_type": "memory_hit", "content": "dead"})
    store.delete(dead_id)

    # Default: tombstones filtered out
    live_only = store.list_items(item_type="memory_hit")
    assert len(live_only) == 1
    assert live_only[0]["deleted"] is False

    # include_deleted: tombstones surfaced as skeleton records
    with_tomb = store.list_items(item_type="memory_hit", include_deleted=True)
    assert len(with_tomb) == 2
    tomb = next(i for i in with_tomb if i.get("deleted"))
    assert tomb["item_id"] == dead_id
    assert tomb["deleted"] is True
    assert "deleted_at" in tomb


# ---------------------------------------------------------------------------
# run_id path traversal
# ---------------------------------------------------------------------------

def test_run_id_rejects_path_traversal(monkeypatch, tmp_path):
    """run_id with `..` or `/` must not escape the workspace runs dir."""
    from workspace import run_store
    from workspace.manager import ensure_workspace

    monkeypatch.setattr(run_store, "WS_ROOT", tmp_path)
    monkeypatch.setattr("workspace.manager.WS_ROOT", tmp_path)

    # ensure_workspace creates the workspace dir
    ensure_workspace("default")

    bad_inputs = [
        "../../etc/passwd",
        "../escape",
        "abc/../etc",
        "name with space",
        "name\x00null",
        "../../../tmp/x",
        ".",
        "..",
    ]
    for raw in bad_inputs:
        # _safe_run_id should always return a safe value
        result = run_store._safe_run_id(raw)
        assert "/" not in result
        assert "\\" not in result
        assert "\x00" not in result
        assert result not in (".", "..")


def test_run_id_accepts_valid_inputs():
    from workspace.run_store import _safe_run_id
    from workspace.ids import validate_run_id

    valid = ["run_123", "abc-123", "abc.def", "req_abc123def456"]
    for raw in valid:
        assert _safe_run_id(raw) == raw
        validate_run_id(raw)  # should not raise


def test_validate_run_id_blocks_dangerous():
    from workspace.ids import validate_run_id
    with pytest.raises(ValueError):
        validate_run_id("../escape")
    with pytest.raises(ValueError):
        validate_run_id("a/b")
    with pytest.raises(ValueError):
        validate_run_id("a\x00b")
    with pytest.raises(ValueError):
        validate_run_id("a" * 200)
    with pytest.raises(ValueError):
        validate_run_id("")


# ---------------------------------------------------------------------------
# session_id validation now matches ids.py
# ---------------------------------------------------------------------------

def test_session_store_uses_canonical_validator():
    """Reserved names like 'default' must be rejected by session path."""
    from workspace.session_store import _session_path
    with pytest.raises(ValueError):
        _session_path("default", "default")
    with pytest.raises(ValueError):
        _session_path(".", "default")
    with pytest.raises(ValueError):
        _session_path("a" * 100, "default")
    with pytest.raises(ValueError):
        _session_path("a/b", "default")


# ---------------------------------------------------------------------------
# schema_registry includes trace_id/run_id/tags
# ---------------------------------------------------------------------------

def test_schema_registry_includes_trace_id():
    from context.schema_registry import _COMMON_FIELDS
    assert "trace_id" in _COMMON_FIELDS
    assert "run_id" in _COMMON_FIELDS
    assert "tags" in _COMMON_FIELDS
    assert "workspace_id" in _COMMON_FIELDS
    assert "created_at" in _COMMON_FIELDS


def test_strip_by_schema_preserves_trace_id():
    from context.schema_registry import strip_by_schema
    item = {
        "item_id": "ci_1",
        "item_type": "memory_hit",
        "content": "hello",
        "trace_id": "trace-abc",
        "run_id": "run_xyz",
        "tags": ["a", "b"],
    }
    stripped = strip_by_schema(item)
    assert stripped.get("trace_id") == "trace-abc"
    assert stripped.get("run_id") == "run_xyz"
    assert stripped.get("tags") == ["a", "b"]


# ---------------------------------------------------------------------------
# context_store timestamps are UTC ISO 8601
# ---------------------------------------------------------------------------

def test_context_store_timestamps_are_utc_iso(monkeypatch, tmp_path):
    from context import context_store as cs

    monkeypatch.setattr(cs, "_ws_root", lambda ws="default": tmp_path / ws / "context")
    store = cs.ContextStore("default")
    item_id = store.put({"item_type": "memory_hit", "content": "x"})
    item = store.get(item_id)
    ts = item["created_at"]
    # ISO 8601 UTC ends with +00:00
    assert "T" in ts
    assert ts.endswith("+00:00") or ts.endswith("Z"), f"expected UTC ISO, got {ts}"


# ---------------------------------------------------------------------------
# workspace state.json atomic write
# ---------------------------------------------------------------------------

def test_state_json_atomic_write(monkeypatch, tmp_path):
    """If write fails midway, state.json must not be corrupted."""
    from workspace import manager

    monkeypatch.setattr(manager, "WS_ROOT", tmp_path)
    manager.ensure_workspace("default")

    state_path = tmp_path / "default" / "sys" / "state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text('{"old": true}')

    real_os_open = manager.os.open
    def boom(path, *args, **kwargs):
        if str(path).endswith(".tmp"):
            raise OSError("simulated disk full")
        return real_os_open(path, *args, **kwargs)
    monkeypatch.setattr(manager.os, "open", boom)

    with pytest.raises(OSError):
        manager._atomic_write_text(state_path, '{"new": true}')

    # Original untouched
    assert state_path.read_text() == '{"old": true}'
    assert not state_path.with_suffix(state_path.suffix + ".tmp").exists()


def test_state_json_atomic_write_success(monkeypatch, tmp_path):
    from workspace import manager
    monkeypatch.setattr(manager, "WS_ROOT", tmp_path)
    manager.ensure_workspace("default")
    state_path = tmp_path / "default" / "sys" / "state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    manager._atomic_write_text(state_path, '{"new": true}')
    assert state_path.read_text() == '{"new": true}'
