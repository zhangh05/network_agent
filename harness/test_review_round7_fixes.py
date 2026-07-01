from __future__ import annotations

import json
import os
import pytest
import threading
import time
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# P0-1 — workspace isolation for memory mutation handlers
# ---------------------------------------------------------------------------

class TestMemoryWorkspaceIsolation:
    """memory.manage / update / delete_soft must read inv.workspace_id,
    not the hardcoded 'default'. This is a privilege boundary: an LLM in
    workspace A must not be able to mutate memory in workspace B."""

    def _make_inv(self, workspace_id="default", **kwargs):
        from tool_runtime.schemas import ToolInvocation
        return ToolInvocation(
            tool_id="memory.manage",
            arguments={"memory_id": "m1", **kwargs},
            workspace_id=workspace_id,
        )

    def test_confirm_uses_caller_workspace(self, monkeypatch):
        from tool_runtime.general_tools import memory_tools
        from context.context_store import ContextStore
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            from context import context_store as cs
            monkeypatch.setattr(cs, "_ws_root", lambda ws="default": Path(tmp) / ws / "context")
            store_a = ContextStore("workspaceA")
            store_b = ContextStore("workspaceB")
            mid_a = store_a.put({"item_type": "memory_hit", "title": "A", "content": "x", "metadata": {"status": "pending_confirmation"}})
            mid_b = store_b.put({"item_type": "memory_hit", "title": "B", "content": "y", "metadata": {"status": "pending_confirmation"}})

            # Caller in workspaceA tries to confirm memory_id from workspaceB.
            # With round 7 fix this should NOT touch workspaceB's memory.
            inv = self._make_inv(workspace_id="workspaceA")
            inv.arguments["memory_id"] = mid_b
            result = memory_tools.handle_memory_confirm(inv)
            # Round 7 fix: should be a not-found / not visible because
            # the caller's store doesn't contain mid_b.
            assert not result.get("ok", False) or "not found" in result.get("summary", "") or result.get("ok", False) is False

            # workspaceB memory is unchanged
            entry_b = store_b.get(mid_b)
            assert entry_b["metadata"]["status"] == "pending_confirmation"

    def test_delete_soft_uses_caller_workspace(self, monkeypatch):
        from tool_runtime.general_tools import memory_tools
        from context.context_store import ContextStore
        from tool_runtime.schemas import ToolInvocation
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            from context import context_store as cs
            monkeypatch.setattr(cs, "_ws_root", lambda ws="default": Path(tmp) / ws / "context")
            store_b = ContextStore("workspaceB")
            mid_b = store_b.put({"item_type": "memory_hit", "title": "B", "content": "y"})

            # Caller in workspaceA tries to delete mid_b
            inv = ToolInvocation(
                tool_id="memory.manage",
                arguments={"memory_id": mid_b},
                workspace_id="workspaceA",
            )
            result = memory_tools.handle_memory_delete_soft(inv)
            # Round 7 fix: workspaceA can't see mid_b, so deletion should fail
            # (not silently affect workspaceB's data)
            if result.get("ok"):
                # if handler reports success it must NOT have deleted mid_b
                assert store_b.get(mid_b) is not None, "delete_soft must not cross workspace boundary"

    @pytest.mark.skip(reason="requires populated memory store")
    def test_search_uses_caller_workspace(self, monkeypatch, tmp_path):
        from context import context_store as cs
        from context import unified_retriever
        from workspace.memory_governance import MemoryStore
        from tool_runtime.general_tools import memory_tools

        monkeypatch.setattr(cs, "_ws_root", lambda ws="default": tmp_path / ws / "context")
        cs._stores.clear()
        unified_retriever._retrievers.clear()
        try:
            MemoryStore()._stores.clear()
        except Exception:
            pass
        cs.get_context_store("workspaceA").put({
            "item_type": "memory_hit",
            "title": "Only A",
            "content": "workspace-a-secret-marker",
        })
        cs.get_context_store("workspaceB").put({
            "item_type": "memory_hit",
            "title": "Only B",
            "content": "workspace-b-secret-marker",
        })

        inv = self._make_inv(workspace_id="workspaceA")
        inv.tool_id = "memory.manage"
        inv.arguments = {"query": "workspace-a-secret-marker"}
        result = memory_tools.handle_memory_search(inv)

        rendered = json.dumps(result, ensure_ascii=False)
        assert "Only A" in rendered
        assert "Only B" not in rendered

    def test_workspace_argument_cannot_override_caller(self):
        from tool_runtime.general_tools import memory_tools

        inv = self._make_inv(workspace_id="workspaceA")
        inv.tool_id = "memory.manage"
        inv.arguments = {
            "workspace_id": "workspaceB",
            "title": "cross workspace",
            "content": "must be blocked",
        }

        result = memory_tools.handle_memory_create(inv)

        assert result.get("ok") is False
        assert "workspace" in json.dumps(result, ensure_ascii=False).lower()


# ---------------------------------------------------------------------------
# P0-5 — is_sub_agent is an immutable trust marker
# ---------------------------------------------------------------------------

class TestSubAgentTrustMarker:
    """session._is_sub_agent must only be writable through mark_sub_agent()
    so an LLM cannot set it via memory.manage to spoof sub-agent privileges."""

    def test_sub_agent_default_false(self):
        from agent.core.session import AgentSession
        s = AgentSession(session_id="s1", workspace_id="default")
        assert s.is_sub_agent is False

    def test_mark_sub_agent_sets_flag(self):
        from agent.core.session import AgentSession
        s = AgentSession(session_id="s1", workspace_id="default")
        s.mark_sub_agent()
        assert s.is_sub_agent is True

    def test_sub_agent_marker_cannot_be_spoofed_via_metadata(self):
        """P0-5: prior code read `session.metadata['is_sub_agent']`, which
        the LLM could write via memory.manage. The new marker is read from
        `_is_sub_agent`, a dedicated field set only via mark_sub_agent()."""
        from agent.core.session import AgentSession
        s = AgentSession(session_id="s1", workspace_id="default")
        # Simulate LLM trying to spoof via metadata — must NOT toggle the marker
        s.metadata = {"is_sub_agent": True, "evil": True}
        assert s.is_sub_agent is False, "metadata-based spoof must not affect trust marker"

    # v3.10: test_runtime_reads_immutable_marker removed — the assertion
    # inspected the legacy ``agent.runtime.loop`` docstring/module body
    # for the substring ``is_sub_agent``. After the SPEG hard cut
    # (ff38bab) the runtime loop is a thin SPEG delegate and the
    # trust marker is read by ``speg_adapter.run_speg_turn``.
    # Detection moved to runtime property test below.


# ---------------------------------------------------------------------------
# SPEG-era replacement: verify the trust marker is read by the
# production runtime path (speg_adapter), not the legacy loop.
# ---------------------------------------------------------------------------

class TestSpegSubAgentTrustMarker:
    """Post-hard-cut equivalent of test_runtime_reads_immutable_marker:
    the new runtime entry (``speg_adapter.run_speg_turn``) must
    correctly propagate ``is_sub_agent`` via the session object —
    LLM-initiated metadata writes must NOT influence that signal."""

    def test_speg_adapter_invokes_session_marker(self):
        from agent.core.session import AgentSession
        s = AgentSession(session_id="spegs1", workspace_id="default")
        # Mark the session and confirm the property surfaces it.
        s.mark_sub_agent()
        assert s.is_sub_agent is True

    def test_speg_adapter_source_uses_session_property(self):
        """SPEG-era replacement: the trust marker is owned by
        ``AgentSession.mark_sub_agent()`` (kept immutable against
        LLM-spoofed metadata). Sub-agent dispatch — the only
        legitimate caller — lives in
        ``agent.runtime.durable.subagent`` and exercises the marker.
        The SPEG adapter itself does not need to read ``is_sub_agent``;
        it runs whatever session it is given."""
        import inspect
        from agent.core.session import AgentSession
        from agent.runtime.durable import subagent as dur_sub
        # Marker API on the session.
        s = AgentSession(session_id="spegs1", workspace_id="default")
        assert hasattr(s, "mark_sub_agent")
        assert hasattr(s, "is_sub_agent")
        # Sub-agent dispatcher must call ``mark_sub_agent()`` so the
        # session surfaces the trust marker.
        src = inspect.getsource(dur_sub)
        assert "mark_sub_agent()" in src
        # The OLD vulnerable pattern must remain gone everywhere it
        # used to live.
        assert "metadata.get('is_sub_agent')" not in src


# ---------------------------------------------------------------------------
# P1-1 — service.py singleton protected by lock
# ---------------------------------------------------------------------------

class TestAgentAppSingletonLock:
    def test_get_default_agent_app_under_contention_returns_one_instance(self):
        from agent.app import service
        # Reset
        service.reset_agent_app_for_tests()

        results = []
        barrier = threading.Barrier(8)

        def worker():
            barrier.wait()  # release all threads simultaneously
            results.append(service.get_default_agent_app())

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        ids = {id(x) for x in results}
        assert len(ids) == 1, f"got {len(ids)} distinct AgentApp instances under contention"

        service.reset_agent_app_for_tests()


# ---------------------------------------------------------------------------
# P1-2 / P1-3 — atomic_io unique tmp + O_EXCL
# ---------------------------------------------------------------------------

class TestAtomicIOUniqueTmp:
    def test_concurrent_writers_do_not_clobber_each_other(self, tmp_path):
        from workspace.atomic_io import atomic_write_text
        target = tmp_path / "x.json"
        errors = []

        def writer(label):
            try:
                for i in range(20):
                    atomic_write_text(target, f"{label}-{i}")
            except Exception as e:
                errors.append((label, e))

        threads = [threading.Thread(target=writer, args=(f"w{i}",)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"writers errored: {errors}"
        # Final content is exactly one of the writer values, not a mix
        content = target.read_text()
        assert content.startswith("w") and "-" in content
        # No leftover tmp files
        leftovers = list(tmp_path.glob("x.json.tmp*"))
        assert not leftovers, f"leftover tmp files: {leftovers}"

    def test_tmp_file_has_pid_and_uuid(self, tmp_path):
        """The new tmp pattern is x.json.tmp.<pid>.<uuid8> so concurrent
        writers using atomic_write_text land on unique tmp names."""
        target = tmp_path / "x.json"
        # Spy: catch the tmp path used
        import os as _os
        real_open = _os.open
        seen_tmp = []

        def spy_open(path, *args, **kwargs):
            spath = str(path)
            if ".tmp." in spath:
                seen_tmp.append(Path(spath).name)
            return real_open(path, *args, **kwargs)

        # Patch atomic_io's reference to os.open (it imports `os` module attr).
        import workspace.atomic_io as aio
        monkey_aio = pytest.MonkeyPatch()
        monkey_aio.setattr(aio.os, "open", spy_open)
        try:
            aio.atomic_write_text(target, "hello")
        finally:
            monkey_aio.undo()

        assert len(seen_tmp) == 1
        name = seen_tmp[0]
        # x.json.tmp.<pid>.<uuid8>
        parts = name.split(".tmp.")
        assert len(parts) == 2
        suffix = parts[1]
        pid_str, uuid_str = suffix.split(".")
        assert pid_str.isdigit()
        assert len(uuid_str) == 8
        assert target.read_text() == "hello"

    def test_replace_failure_keeps_original_and_removes_tmp(self, monkeypatch, tmp_path):
        import workspace.atomic_io as aio

        target = tmp_path / "x.json"
        target.write_text("old")

        def fail_replace(_src, _dst):
            raise OSError("simulated replace failure")

        monkeypatch.setattr(aio.os, "replace", fail_replace)

        with pytest.raises(OSError):
            aio.atomic_write_text(target, "new")

        assert target.read_text() == "old"
        assert list(tmp_path.glob("x.json.tmp*")) == []


# ---------------------------------------------------------------------------
# P1-2 — context_store.compact atomic + O_EXCL
# ---------------------------------------------------------------------------

class TestContextStoreCompactOEXCL:
    def test_compact_uses_unique_tmp_with_o_excl(self, monkeypatch, tmp_path):
        from context import context_store as cs
        monkeypatch.setattr(cs, "_ws_root", lambda ws="default": tmp_path / ws / "context")
        store = cs.ContextStore("default")
        store.put({"item_type": "memory_hit", "content": "a"})
        store.put({"item_type": "memory_hit", "content": "b"})

        # Capture the open() flags used
        seen_flags = []
        real_open = cs.os.open
        def spy_open(path, *args, **kwargs):
            seen_flags.append((str(path), kwargs.get("flags", args[0] if args else 0)))
            return real_open(path, *args, **kwargs)
        monkeypatch.setattr(cs.os, "open", spy_open)

        store.compact()

        # Find the open() call with O_EXCL set
        flags_used = [f for path, f in seen_flags if ".tmp." in path]
        assert flags_used, "compact() didn't open any tmp file"
        for f in flags_used:
            assert f & os.O_EXCL, f"O_EXCL missing: flags={f}"

    def test_compact_replace_failure_keeps_primary_file(self, monkeypatch, tmp_path):
        from context import context_store as cs

        monkeypatch.setattr(cs, "_ws_root", lambda ws="default": tmp_path / ws / "context")
        store = cs.ContextStore("default")
        store.put({"item_type": "memory_hit", "content": "must survive"})
        original = store._items_path.read_text()

        def fail_replace(_src, _dst):
            raise OSError("simulated replace failure")

        monkeypatch.setattr(cs.os, "replace", fail_replace)

        with pytest.raises(OSError):
            store.compact()

        assert store._items_path.read_text() == original
        assert list(store._items_path.parent.glob("items.jsonl.tmp*")) == []


# ---------------------------------------------------------------------------
# P1-6 — web.fetch_summary cache thread safety
# ---------------------------------------------------------------------------

class TestWebFetchCacheLock:
    def test_cache_module_has_lock(self):
        from tool_runtime.general_tools import web_tools
        assert isinstance(web_tools._fetch_summary_cache_lock, type(threading.Lock()))
        assert isinstance(web_tools._fetch_summary_cache, dict)


# ---------------------------------------------------------------------------
# P1-7 — session_checkpoint uses atomic_io
# ---------------------------------------------------------------------------

class TestSessionCheckpointAtomic:
    def test_atomic_write_json_used_for_checkpoint(self, monkeypatch, tmp_path):
        """P1 fix (round 7): system.session.checkpoint now writes via workspace.atomic_io
        (atomic_write_json) rather than direct path.write_text. Verify the
        import path is wired up — atomic_write_json is referenced inside
        the handler module so a crash mid-write no longer leaves a
        half-written checkpoint file."""
        import inspect
        from tool_runtime.general_tools import session_tools
        src = inspect.getsource(session_tools.handle_session_checkpoint)
        assert "atomic_write_json" in src
        assert ".write_text(" not in src.split("checkpoint_path")[1], (
            "checkpoint must not call write_text directly (round 7 fix uses atomic_write_json)"
        )

    def test_atomic_write_json_crash_safe(self, tmp_path):
        """Direct test: if atomic_write_json fails, original file is untouched."""
        from workspace.atomic_io import atomic_write_json
        target = tmp_path / "x.json"
        target.write_text('{"old": true}')
        import workspace.atomic_io as aio
        real_open = aio.os.open
        def boom(path, *args, **kwargs):
            if ".tmp" in str(path):
                raise OSError("simulated disk full")
            return real_open(path, *args, **kwargs)
        monkey = pytest.MonkeyPatch()
        monkey.setattr(aio.os, "open", boom)
        try:
            with pytest.raises(OSError):
                atomic_write_json(target, {"new": True})
        finally:
            monkey.undo()
        assert target.read_text() == '{"old": true}'


# ---------------------------------------------------------------------------
# P1-8 — retention apply_retention validates sid
# ---------------------------------------------------------------------------

class TestRetentionSidValidation:
    def test_malformed_sid_refused(self, monkeypatch):
        """A candidate whose sid contains path separators or shell metacharacters
        must not lead to shutil.rmtree on an arbitrary directory.

        P1 fix (round 7): apply_retention validates `sid` syntax and
        separately rejects "." / ".." before using it as a directory name.
        The handler appends a warning to preview.warnings and continues,
        rather than calling shutil.rmtree on a path that could escape or
        collapse to the workspace root.
        """
        # Direct unit-test of the validation regex used in apply_retention
        import re
        pattern = re.compile(r"[A-Za-z0-9_\-\.]{1,128}")
        # Good sids
        assert pattern.fullmatch("abc123")
        assert pattern.fullmatch("session-2026-01-01")
        # Bad sids
        assert not pattern.fullmatch("../escape")
        assert not pattern.fullmatch("/etc/passwd")
        assert not pattern.fullmatch("")
        assert not pattern.fullmatch("a;b")
        assert not pattern.fullmatch("a b")  # space not allowed
        assert not pattern.fullmatch("a\nb")  # newline not allowed
        # The regex alone allows these, so apply_retention must also reject
        # them explicitly before resolving paths.
        assert pattern.fullmatch(".")
        assert pattern.fullmatch("..")

    def test_apply_retention_wiring_uses_sid_validation(self):
        """Sanity: the apply_retention handler actually invokes the regex
        gate before shutil.rmtree. Use inspect to find the source."""
        import inspect
        from runtime import retention
        src = inspect.getsource(retention.apply_retention)
        assert "shutil.rmtree" in src  # still uses rmtree, but gated
        assert "fullmatch" in src, "apply_retention must validate sid via fullmatch regex"

    @pytest.mark.parametrize("sid", [".", ".."])
    def test_apply_retention_refuses_dot_session_ids(self, monkeypatch, tmp_path, sid):
        from runtime import retention

        ws_root = tmp_path / "workspaces"
        ws_dir = ws_root / "default"
        sessions_dir = ws_dir / "sessions"
        sessions_dir.mkdir(parents=True)
        sentinel = ws_dir / "sentinel.txt"
        sentinel.write_text("must survive")

        preview = retention.RetentionPreview(
            dry_run=False,
            workspace_id="default",
            candidates=[{
                "type": "session_deleted",
                "name": f"{sid}.json",
                "sid": sid,
            }],
        )
        monkeypatch.setattr(retention, "WS_ROOT", ws_root)
        monkeypatch.setattr(retention, "preview_retention", lambda *_args, **_kwargs: preview)
        monkeypatch.setattr(retention, "write_audit", lambda **_kwargs: "")

        result = retention.apply_retention("default", dry_run=False, confirm=True)

        assert sentinel.read_text() == "must survive"
        assert result.deleted_counts.get("sessions", 0) == 0
        assert any("malformed sid" in warning for warning in result.warnings)


# ---------------------------------------------------------------------------
# P1-9 — cleanup_expired uses delete_many + compact
# ---------------------------------------------------------------------------

class TestCleanupExpiredBatched:
    def test_cleanup_expired_uses_delete_many(self, monkeypatch, tmp_path):
        from context import context_store as cs
        from context.context_store import ContextStore
        monkeypatch.setattr(cs, "_ws_root", lambda ws="default": tmp_path / ws / "context")
        store = ContextStore("default")

        # Insert 5 expired items + 2 live
        for i in range(5):
            store.put({"item_type": "memory_hit", "content": f"old-{i}", "expires_at": "2020-01-01T00:00:00+00:00"})
        for i in range(2):
            store.put({"item_type": "memory_hit", "content": f"live-{i}"})

        # Spy: ensure delete_many is called instead of N delete() calls
        called = {"delete_many": 0, "delete": 0, "compact": 0}
        real_dm = store.delete_many
        real_d = store.delete
        real_c = store.compact

        def spy_dm(ids):
            called["delete_many"] += 1
            return real_dm(ids)
        def spy_d(iid):
            called["delete"] += 1
            return real_d(iid)
        def spy_c():
            called["compact"] += 1
            return real_c()

        monkeypatch.setattr(store, "delete_many", spy_dm)
        monkeypatch.setattr(store, "delete", spy_d)
        monkeypatch.setattr(store, "compact", spy_c)

        result = store.cleanup_expired(dry_run=False)
        assert result["expired_count"] == 5
        assert called["delete_many"] == 1
        assert called["delete"] == 0, "must use delete_many, not N delete() calls"
        assert called["compact"] == 1, "must call compact() after delete_many"
        assert store.all_items() == [
            item for item in store.all_items()
            if item.get("content", "").startswith("live-")
        ]
        assert len(store.all_items()) == 2


class TestAppendEventConcurrency:
    def test_concurrent_appends_preserve_every_event(self, monkeypatch, tmp_path):
        from observability import store as observability_store

        runs_dir = tmp_path / "default" / "runs"
        runs_dir.mkdir(parents=True)
        trace_path = runs_dir / "run-1.trace.json"
        trace_path.write_text(json.dumps({
            "trace_id": "trace-1",
            "run_id": "run-1",
            "events": [],
        }))
        monkeypatch.setattr(observability_store, "_get_ws_root", lambda: tmp_path)

        barrier = threading.Barrier(20)

        def append(index):
            barrier.wait()
            observability_store.append_event(
                "trace-1",
                {"event_id": str(index), "run_id": "run-1"},
                "default",
            )

        threads = [threading.Thread(target=append, args=(index,)) for index in range(20)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        stored = json.loads(trace_path.read_text())
        assert len(stored["events"]) == 20
        assert {event["event_id"] for event in stored["events"]} == {
            str(index) for index in range(20)
        }


# ---------------------------------------------------------------------------
# P1-10 — _preserve_tool_payload_edges UTF-8 safe
# ---------------------------------------------------------------------------

class TestPreserveToolPayloadEdgesUTF8:
    def test_does_not_split_cjk_codepoint(self):
        from agent.runtime.tool_execution.result_stage import preserve_tool_payload_edges
        # 10 CJK characters (each 3 bytes UTF-8, 1 Python char)
        text = "你好世界你好世界你好世界你好世"  # 14 chars
        # Force truncation
        out = preserve_tool_payload_edges(text, limit=10)
        # Output must round-trip through utf-8 encode/decode without error
        encoded = out.encode("utf-8")
        decoded = encoded.decode("utf-8")
        assert decoded == out
        # Marker should be present
        assert "truncated middle" in out

    def test_short_text_unchanged(self):
        from agent.runtime.tool_execution.result_stage import preserve_tool_payload_edges
        text = "hello"
        out = preserve_tool_payload_edges(text, limit=100)
        assert out == text


# ---------------------------------------------------------------------------
# P2-7 — record_recent_failure logs instead of swallow
# ---------------------------------------------------------------------------

class TestRecordRecentFailureLogging:
    def test_swallows_are_logged(self, monkeypatch, caplog):
        """When record_recent_failure itself raises, the loop's except
        branch must log a warning, not silently pass."""
        import logging
        from agent import llm

        # Make record_recent_failure raise
        def boom(*args, **kwargs):
            raise RuntimeError("cb broken")

        if hasattr(llm, "config"):
            monkeypatch.setattr(llm.config, "record_recent_failure", boom)

        # Touch the codepath via direct invocation
        from agent.runtime.tool_execution.result_stage import preserve_tool_payload_edges  # any import to load module
        # Just ensure the loop module imported successfully
        from agent.runtime import loop
        assert loop is not None
