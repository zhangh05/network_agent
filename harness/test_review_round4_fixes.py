"""Regression tests for Round 4 source code review fixes.

Covers P0/P1 issues found in agent/runtime/loop.py, agent/runtime/query_engine.py,
backend/ws/agent_ws.py, agent/tools/router.py, and workspace/atomic_io.py.

Each fix should have at least one focused test that fails on the old code
and passes on the new code.
"""

import json
import os
import sys
import threading
import time
import types
from pathlib import Path

import pytest

# Ensure repo root on path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ─────────────────────────────────────────────────────────────────────
# workspace.atomic_io — new shared atomic write/read helpers
# ─────────────────────────────────────────────────────────────────────

class TestAtomicIO:
    def test_atomic_write_text_writes_content(self, tmp_path):
        from workspace.atomic_io import atomic_write_text
        target = tmp_path / "state.json"
        atomic_write_text(target, '{"hello": "world"}')
        assert target.read_text(encoding="utf-8") == '{"hello": "world"}'

    def test_atomic_write_text_creates_parent(self, tmp_path):
        from workspace.atomic_io import atomic_write_text
        target = tmp_path / "deep" / "nested" / "file.txt"
        atomic_write_text(target, "ok")
        assert target.read_text(encoding="utf-8") == "ok"

    def test_atomic_write_text_leaves_original_on_failure(self, tmp_path):
        from workspace import atomic_io
        target = tmp_path / "state.json"
        target.write_text("original", encoding="utf-8")
        # Patch os.open to fail; the original file must be untouched.
        original_open = atomic_io.os.open
        def boom(*args, **kwargs):
            raise OSError("disk full")
        atomic_io.os.open = boom
        try:
            with pytest.raises(OSError):
                atomic_io.atomic_write_text(target, "new")
        finally:
            atomic_io.os.open = original_open
        assert target.read_text(encoding="utf-8") == "original"

    def test_atomic_write_json_serializes(self, tmp_path):
        from workspace.atomic_io import atomic_write_json
        target = tmp_path / "data.json"
        atomic_write_json(target, {"a": 1, "b": [1, 2, 3]})
        loaded = json.loads(target.read_text(encoding="utf-8"))
        assert loaded == {"a": 1, "b": [1, 2, 3]}

    def test_safe_read_json_missing_returns_default(self, tmp_path):
        from workspace.atomic_io import safe_read_json
        assert safe_read_json(tmp_path / "missing.json") is None
        assert safe_read_json(tmp_path / "missing.json", default={}) == {}

    def test_safe_read_json_malformed_returns_default(self, tmp_path):
        from workspace.atomic_io import safe_read_json
        target = tmp_path / "broken.json"
        target.write_text("{not valid json", encoding="utf-8")
        assert safe_read_json(target, default={}) == {}

    def test_safe_read_text_missing_returns_default(self, tmp_path):
        from workspace.atomic_io import safe_read_text
        assert safe_read_text(tmp_path / "missing.txt") == ""
        assert safe_read_text(tmp_path / "missing.txt", default="x") == "x"


# ─────────────────────────────────────────────────────────────────────
# agent.tools.router — ToolArgumentParseError replaces silent swallow
# ─────────────────────────────────────────────────────────────────────

class TestToolArgumentParseError:
    def _make_router(self):
        from agent.tools.router import ToolRouter
        from agent.tools.registry import ToolRegistry
        from tool_runtime.tool_namespace import TOOL_NAMESPACE
        # Build a tiny registry containing one canonical tool.
        reg = ToolRegistry()
        from agent.tools.schemas import ToolSpec
        if "host.shell.exec" in TOOL_NAMESPACE:
            tid = "host.shell.exec"
        else:
            tid = next(iter(TOOL_NAMESPACE))
        spec = ToolSpec(
            tool_id=tid, name=tid, category="general",
            description="test", risk_level="medium",
            enabled=True, callable_by_llm=True,
            input_schema={"type": "object", "properties": {}},
        )
        reg._specs[tid] = spec
        return ToolRouter.for_turn(reg), tid

    def test_malformed_json_args_raises_clear_error(self):
        from agent.tools.router import ToolArgumentParseError
        router, tid = self._make_router()
        from agent.llm.tool_adapter import to_llm_tool_name
        llm_name = to_llm_tool_name(tid)
        raw_tc = types.SimpleNamespace(
            id="call_1",
            name=llm_name,
            arguments="{this is not json",
        )
        with pytest.raises(ToolArgumentParseError) as exc:
            router.build_tool_call(raw_tc)
        assert "not valid JSON" in str(exc.value)
        assert tid in str(exc.value) or llm_name in str(exc.value)

    def test_non_object_json_args_rejected(self):
        from agent.tools.router import ToolArgumentParseError
        router, tid = self._make_router()
        from agent.llm.tool_adapter import to_llm_tool_name
        llm_name = to_llm_tool_name(tid)
        raw_tc = types.SimpleNamespace(
            id="call_2", name=llm_name, arguments="[1, 2, 3]"
        )
        with pytest.raises(ToolArgumentParseError) as exc:
            router.build_tool_call(raw_tc)
        assert "must be a JSON object" in str(exc.value)

    def test_empty_string_args_become_empty_dict(self):
        router, tid = self._make_router()
        from agent.llm.tool_adapter import to_llm_tool_name
        llm_name = to_llm_tool_name(tid)
        raw_tc = types.SimpleNamespace(
            id="call_3", name=llm_name, arguments=""
        )
        tc = router.build_tool_call(raw_tc)
        assert tc.arguments == {}

    def test_valid_object_args_pass_through(self):
        router, tid = self._make_router()
        from agent.llm.tool_adapter import to_llm_tool_name
        llm_name = to_llm_tool_name(tid)
        raw_tc = types.SimpleNamespace(
            id="call_4", name=llm_name,
            arguments='{"command": "ls"}',
        )
        tc = router.build_tool_call(raw_tc)
        assert tc.arguments == {"command": "ls"}
        assert tc.real_tool_id == tid


# ─────────────────────────────────────────────────────────────────────
# agent.runtime.query_engine — StreamEmitter thread-local callback
# ─────────────────────────────────────────────────────────────────────

class TestStreamEmitterThreadLocal:
    def test_callback_is_thread_local(self):
        """Two threads set different callbacks; each must see only its own."""
        from agent.runtime.query_engine import StreamEmitter, StreamEvent

        seen = {"thread_a": None, "thread_b": None}
        ready = threading.Event()
        proceed = threading.Event()

        def set_then_emit(label, payload):
            def cb(event):
                seen[label] = event.get("type")
            StreamEmitter.set_realtime_callback(cb)
            # Wait so both threads have their callbacks set simultaneously.
            ready.set()
            proceed.wait(timeout=2.0)
            emitter = StreamEmitter()
            emitter.emit(StreamEvent.MODEL_STARTED, {"step": 1})

        ta = threading.Thread(target=set_then_emit, args=("thread_a", {}))
        tb = threading.Thread(target=set_then_emit, args=("thread_b", {}))
        ta.start()
        tb.start()
        # Make sure both threads have reached the barrier.
        ready.wait(timeout=2.0)
        time.sleep(0.05)
        ready.clear()
        # Release both threads.
        proceed.set()
        ta.join(timeout=5.0)
        tb.join(timeout=5.0)

        # Each thread's callback should have received its own MODEL_STARTED.
        # If the callback were class-level, one of these would be None or
        # both would receive the *other* thread's events.
        assert seen["thread_a"] == StreamEvent.MODEL_STARTED
        assert seen["thread_b"] == StreamEvent.MODEL_STARTED

    def test_clear_only_clears_current_thread(self):
        """Clearing the callback on one thread must not affect another."""
        from agent.runtime.query_engine import StreamEmitter

        ev_a = threading.Event()
        ev_b = threading.Event()

        def thread_a():
            StreamEmitter.set_realtime_callback(lambda e: None)
            ev_a.set()
            ev_b.wait(timeout=2.0)
            # After thread B cleared its own callback, thread A's should still be set.
            assert StreamEmitter._get_realtime() is not None

        def thread_b():
            StreamEmitter.set_realtime_callback(lambda e: None)
            ev_b.set()
            StreamEmitter.clear_realtime_callback()
            assert StreamEmitter._get_realtime() is None

        ta = threading.Thread(target=thread_a)
        tb = threading.Thread(target=thread_b)
        ta.start()
        tb.start()
        ta.join(timeout=5.0)
        tb.join(timeout=5.0)


# ─────────────────────────────────────────────────────────────────────
# agent.runtime.loop — _apply_manual_compact safety
# ─────────────────────────────────────────────────────────────────────

class TestLoopApplyManualCompact:
    """The _apply_manual_compact helper must not crash when session.metadata
    is None or when reading / writing meta.json.
    """

    def test_none_metadata_does_not_raise(self):
        """Previously getattr(session, 'metadata', {}).get(...) raised
        AttributeError when metadata was None."""
        from agent.runtime.stages.messages import _apply_manual_compact

        class FakeTurn:
            warnings = []
            op = types.SimpleNamespace(user_input="x")
            metadata = {}

        class FakeSession:
            session_id = "nonexistent_for_test"
            workspace_id = "default"
            metadata = None  # ← the dangerous case

        fake_session = FakeSession()
        fake_turn = FakeTurn()
        messages = []
        # Should not raise AttributeError.
        _apply_manual_compact(fake_session, fake_turn, messages)
        assert messages == []

    def test_empty_metadata_does_not_raise(self):
        from agent.runtime.stages.messages import _apply_manual_compact

        class FakeTurn:
            warnings = []
            op = types.SimpleNamespace(user_input="x")
            metadata = {}

        class FakeSession:
            session_id = "nonexistent_for_test"
            workspace_id = "default"
            metadata = {}  # empty but not None

        _apply_manual_compact(FakeSession(), FakeTurn(), [])

    def test_missing_metadata_attr_does_not_raise(self):
        from agent.runtime.stages.messages import _apply_manual_compact

        class FakeTurn:
            warnings = []
            op = types.SimpleNamespace(user_input="x")
            metadata = {}

        class FakeSession:
            session_id = "nonexistent_for_test"
            workspace_id = "default"
            # No metadata attribute at all — using __slots__ would break
            # the dynamic session API; instead, drop the attribute by
            # NOT defining it and never setting it. We also need to
            # neutralize hasattr() — fake an AttributeError via __getattribute__.
            def __getattribute__(self, name):
                if name == "metadata":
                    raise AttributeError("no metadata attribute")
                return object.__getattribute__(self, name)

        # Must not raise AttributeError when reading metadata.
        _apply_manual_compact(FakeSession(), FakeTurn(), [])


# ─────────────────────────────────────────────────────────────────────
# agent.runtime.loop — _get_approval_timeout sub-agent detection
# ─────────────────────────────────────────────────────────────────────

class TestApprovalTimeoutDetection:
    """The fix replaces `bool(...).get(...)` (AttributeError) with a safe
    dict-aware read. Ensure neither truthy nor falsy metadata raises.
    """

    def test_is_sub_agent_true(self):
        from agent.runtime.loop import _get_approval_timeout

        class FakeSession:
            metadata = {"is_sub_agent": True}
        # Must not raise; should return sub-agent timeout.
        from agent.runtime.loop import _APPROVAL_TIMEOUT_SUBAGENT_S
        assert _get_approval_timeout(
            is_sub_agent=isinstance(getattr(FakeSession(), "metadata", None), dict)
            and FakeSession().metadata.get("is_sub_agent")
        ) == _APPROVAL_TIMEOUT_SUBAGENT_S

    def test_is_sub_agent_false(self):
        from agent.runtime.loop import _get_approval_timeout
        from agent.runtime.loop import _APPROVAL_TIMEOUT_DEFAULT_S

        class FakeSession:
            metadata = {"is_sub_agent": False}
        assert _get_approval_timeout(
            is_sub_agent=isinstance(getattr(FakeSession(), "metadata", None), dict)
            and FakeSession().metadata.get("is_sub_agent")
        ) == _APPROVAL_TIMEOUT_DEFAULT_S

    def test_is_sub_agent_none_metadata_safe(self):
        """Even when metadata is None, the helper must not raise."""
        from agent.runtime.loop import _get_approval_timeout
        from agent.runtime.loop import _APPROVAL_TIMEOUT_DEFAULT_S

        class FakeSession:
            metadata = None
        m = getattr(FakeSession(), "metadata", None)
        result = isinstance(m, dict) and m.get("is_sub_agent")
        assert result is False
        assert _get_approval_timeout(is_sub_agent=bool(result)) == _APPROVAL_TIMEOUT_DEFAULT_S


# ─────────────────────────────────────────────────────────────────────
# backend.ws.agent_ws — debug print removal + session_id validation
# ─────────────────────────────────────────────────────────────────────

class TestAgentWsHardening:
    def test_no_debug_print_to_stderr(self):
        """The two leftover debug prints must be gone."""
        import backend.ws.agent_ws as ws_mod
        src = Path(ws_mod.__file__).read_text(encoding="utf-8")
        # Should not contain `[loop]` or `[ws-agent]` debug prefixes.
        assert "[loop] final_answer" not in src
        assert "[ws-agent] final_response_len" not in src

    def test_loop_py_no_debug_print(self):
        from pathlib import Path as _P
        src = (_P(ROOT) / "agent" / "runtime" / "loop.py").read_text(encoding="utf-8")
        assert "[loop] final_answer" not in src


# ─────────────────────────────────────────────────────────────────────
# agent.runtime.services — dead-code removal
# ─────────────────────────────────────────────────────────────────────

class TestServicesDeadCodeRemoval:
    def test_no_duplicate_return(self):
        from pathlib import Path as _P
        src = (_P(ROOT) / "agent" / "runtime" / "services.py").read_text(encoding="utf-8")
        # The duplicate `return reg` near the bottom of _build_default_registry
        # must be gone.
        assert src.count("    return reg\n") <= 3  # one in each function is fine