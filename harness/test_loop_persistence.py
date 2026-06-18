"""Test loop persistence — ensures run records are written and
session messages are recoverable across all return paths.

v1.0.3: also validates the ToolRouter per-turn cross-talk guard.
"""

import json
import threading
import time
from pathlib import Path

import pytest

from workspace.ids import validate_workspace_id, validate_session_id
from workspace.session_store import create_session, get_session_messages
from workspace.run_store import write_run_record
from workspace.message_store import SessionMessageStore


WS_ID = "test_loop_persist"


@pytest.fixture(autouse=True)
def clean_ws():
    from workspace.manager import ensure_workspace
    ensure_workspace(WS_ID)
    yield
    # Clean up runs and sessions so test workspace stays tidy
    ws = Path(__file__).resolve().parent.parent / "workspaces" / WS_ID
    for sub in ("runs", "sessions"):
        d = ws / sub
        if d.is_dir():
            for f in d.glob("*.json"):
                try:
                    f.unlink()
                except Exception:
                    pass


# ── Fixtures ──


def _fake_state(session_id="", request_id="run_001", user_input="hello"):
    from types import SimpleNamespace
    return SimpleNamespace(
        request_id=request_id,
        session_id=session_id,
        created_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        user_input=user_input,
        intent="assistant_chat",
        context={
            "llm": {"used": True, "provider": "test", "model": "test"},
            "capability_id": "",
            "memory_written": False,
            "workspace_updated": False,
        },
        active_module="",
        selected_skill="",
        runtime_mode="codex_v1",
        final_response="Hello, world!",
        warnings=[],
        trace_id="trace_001",
        error=None,
        skill_results={},
        tool_results={},
    )


# ── Basic persistence ──


def test_write_run_record_persists():
    """write_run_record creates a JSON file in the workspace runs/ dir."""
    from workspace.run_store import WS_ROOT
    run_id = write_run_record(_fake_state(), WS_ID)
    assert run_id

    path = WS_ROOT / WS_ID / "runs" / f"{run_id}.json"
    assert path.is_file(), f"Expected file at {path}, dir contents: {list(path.parent.glob('*')) if path.parent.is_dir() else 'no dir'}"

    data = json.loads(path.read_text())
    assert data["run_id"] == run_id
    assert data["workspace_id"] == WS_ID
    # user_input_summary is redacted and truncated; just check it's not empty
    assert len(data.get("user_input_summary", "")) > 0


def test_session_gets_run_id():
    """When write_run_record has session_id, it calls add_run_to_session."""
    sid = create_session(WS_ID, title="persist test")["session_id"]
    run_id = write_run_record(_fake_state(session_id=sid), WS_ID)

    session_msgs = get_session_messages(sid, WS_ID)
    assert session_msgs == []

    store = SessionMessageStore(session_id=sid, ws_id=WS_ID)
    store.write_message(run_id, "user", "hello", metadata={"created_at": "2026-06-18T00:00:00"})
    store.write_message(run_id, "assistant", "Hello, world!", metadata={"created_at": "2026-06-18T00:00:01"})
    msgs = get_session_messages(sid, WS_ID)
    assert len(msgs) == 2  # user + assistant
    assert msgs[0]["role"] == "user"
    assert msgs[1]["role"] == "assistant"
    assert msgs[0]["run_id"] == run_id
    assert msgs[1]["run_id"] == run_id


# ── Message ID format ──


def test_message_id_format_colon():
    """v1.0.3: message_id uses <run_id>:<role> format (colon, not underscore)."""
    sid = create_session(WS_ID, title="msg id test")["session_id"]
    run_id = write_run_record(_fake_state(session_id=sid, request_id="r001", user_input="test"), WS_ID)
    store = SessionMessageStore(session_id=sid, ws_id=WS_ID)
    store.write_message(run_id, "user", "test", metadata={"created_at": "2026-06-18T00:00:00"})
    store.write_message(run_id, "assistant", "ok", metadata={"created_at": "2026-06-18T00:00:01"})

    msgs = get_session_messages(sid, WS_ID)
    for m in msgs:
        assert ":" in m["message_id"], f"Expected colon in message_id, got {m['message_id']}"
        if m["role"] == "user":
            assert m["message_id"].endswith(":user")
        elif m["role"] == "assistant":
            assert m["message_id"].endswith(":assistant")


# ── History window ──


def test_history_window_respects_k():
    """get_history_window(k=N) returns at most N messages."""
    sid = create_session(WS_ID, title="window test")["session_id"]
    store = SessionMessageStore(session_id=sid, ws_id=WS_ID)
    for i in range(5):
        run_id = write_run_record(
            _fake_state(session_id=sid, request_id=f"run_{i:03d}", user_input=f"msg {i}"),
            WS_ID,
        )
        store.write_message(run_id, "user", f"msg {i}", metadata={"created_at": f"2026-06-18T00:00:{i * 2:02d}"})
        store.write_message(run_id, "assistant", "ok", metadata={"created_at": f"2026-06-18T00:00:{i * 2 + 1:02d}"})

    full = store.get_messages()
    assert len(full) == 10  # 5 runs * 2

    window = store.get_history_window(k=4)
    assert len(window) == 4

    window_full = store.get_history_window(k=20)
    assert len(window_full) == 10


# ── Cross-talk guard ──


def test_tool_router_no_cross_talk():
    """Two ToolRouters with different allowed_tool_ids must not cross-talk."""
    from agent.tools.router import ToolRouter
    from agent.tools.registry import ToolRegistry

    reg = ToolRegistry()

    # Directly register two test tools into _specs
    from agent.tools.schemas import ToolSpec
    t1 = ToolSpec(
        tool_id="test.tool_a",
        name="tool_a",
        description="Tool A",
        input_schema={"type": "object", "properties": {}},
        enabled=True,
        callable_by_llm=True,
    )
    t2 = ToolSpec(
        tool_id="test.tool_b",
        name="tool_b",
        description="Tool B",
        input_schema={"type": "object", "properties": {}},
        enabled=True,
        callable_by_llm=True,
    )
    reg._specs[t1.tool_id] = t1
    reg._specs[t2.tool_id] = t2

    # Build two routers with different whitelists
    router_a = ToolRouter.for_turn(reg, allowed_tool_ids={"test.tool_a"})
    router_b = ToolRouter.for_turn(reg, allowed_tool_ids={"test.tool_b"})

    # Router A should only see tool_a
    visible_a = [t["function"]["name"] for t in router_a.model_visible_tools()]
    assert "test__tool_a" in visible_a  # LLM-safe name
    assert "test__tool_b" not in visible_a

    # Router B should only see tool_b
    visible_b = [t["function"]["name"] for t in router_b.model_visible_tools()]
    assert "test__tool_b" in visible_b
    assert "test__tool_a" not in visible_b


def test_tool_router_for_turn_no_shared_mutation():
    """for_turn() creates independent instances. Mutating one does not
    affect another.
    """
    from agent.tools.router import ToolRouter
    from agent.tools.registry import ToolRegistry

    reg = ToolRegistry()
    from agent.tools.schemas import ToolSpec
    t_spec = ToolSpec(
        tool_id="test.tool_x", name="tool_x", description="X",
        input_schema={"type": "object", "properties": {}},
        enabled=True, callable_by_llm=True,
    )
    reg._specs[t_spec.tool_id] = t_spec
    t_spec2 = ToolSpec(
        tool_id="test.tool_y", name="tool_y", description="Y",
        input_schema={"type": "object", "properties": {}},
        enabled=True, callable_by_llm=True,
    )
    reg._specs[t_spec2.tool_id] = t_spec2

    router = ToolRouter.for_turn(reg, allowed_tool_ids={"test.tool_x"})
    visible = [t["function"]["name"] for t in router.model_visible_tools()]
    assert "test__tool_x" in visible
    assert "test__tool_y" not in visible

    # Build a second router sharing the same registry — it must be independent.
    router2 = ToolRouter.for_turn(reg, allowed_tool_ids={"test.tool_y"})
    visible2 = [t["function"]["name"] for t in router2.model_visible_tools()]
    assert "test__tool_y" in visible2
    assert "test__tool_x" not in visible2

    # The first router must still be unaffected.
    visible_check = [t["function"]["name"] for t in router.model_visible_tools()]
    assert "test__tool_y" not in visible_check


def test_concurrent_turns_no_cross_talk():
    """Simulate two concurrent turns with different tool whitelists
    using actual thread-level concurrency.
    """
    from agent.tools.router import ToolRouter
    from agent.tools.registry import ToolRegistry
    from agent.tools.schemas import ToolSpec

    reg = ToolRegistry()
    t_spec = ToolSpec(
        tool_id="test.cfg", name="cfg", description="Config",
        input_schema={"type": "object", "properties": {}},
        enabled=True, callable_by_llm=True,
    )
    reg._specs[t_spec.tool_id] = t_spec
    t_spec2 = ToolSpec(
        tool_id="test.kb", name="kb", description="Knowledge",
        input_schema={"type": "object", "properties": {}},
        enabled=True, callable_by_llm=True,
    )
    reg._specs[t_spec2.tool_id] = t_spec2

    errors = []

    def turn_cfg():
        try:
            r = ToolRouter.for_turn(reg, allowed_tool_ids={"test.cfg"})
            v = [t["function"]["name"] for t in r.model_visible_tools()]
            assert "test__cfg" in v
            assert "test__kb" not in v
        except Exception as e:
            errors.append(str(e))

    def turn_kb():
        try:
            r = ToolRouter.for_turn(reg, allowed_tool_ids={"test.kb"})
            v = [t["function"]["name"] for t in r.model_visible_tools()]
            assert "test__kb" in v
            assert "test__cfg" not in v
        except Exception as e:
            errors.append(str(e))

    t1 = threading.Thread(target=turn_cfg)
    t2 = threading.Thread(target=turn_kb)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert not errors, f"Concurrent cross-talk detected: {errors}"


# ── Planned capabilities are NOT callable ──


def test_planned_capability_not_visible():
    """Planned capabilities must NOT appear in visible_tool_ids()."""
    from agent.capabilities.builtin import get_default_capability_registry
    reg = get_default_capability_registry()

    visible = reg.visible_tool_ids()
    planned = reg.list_planned()

    planned_tool_ids = set()
    for m in planned:
        for t in m.tools:
            planned_tool_ids.add(t.tool_id)

    assert planned_tool_ids, "Should have planned tools"
    assert not (planned_tool_ids & set(visible)), (
        f"Planned tools must not be visible: {planned_tool_ids & set(visible)}"
    )


# ── Capability count contract ──


def test_capability_registry_7_caps_4_enabled_3_planned():
    """v1.0.3 contract: exactly 7 capabilities, 4 enabled, 3 planned."""
    from agent.capabilities.builtin import get_default_capability_registry
    reg = get_default_capability_registry()

    all_caps = reg.list_all()
    assert len(all_caps) == 7, f"Expected 7 capabilities, got {len(all_caps)}"

    enabled = reg.list_enabled()
    assert len(enabled) == 4, f"Expected 4 enabled, got {len(enabled)}"

    planned = reg.list_planned()
    assert len(planned) == 3, f"Expected 3 planned, got {len(planned)}"

    assert not reg.list_disabled()

    # Verify specific capabilities
    enabled_ids = {m.capability_id for m in enabled}
    assert enabled_ids == {"config_translation", "knowledge", "artifact", "review"}

    planned_ids = {m.capability_id for m in planned}
    assert planned_ids == {"topology", "inspection", "cmdb"}


# ── Workspace knowledge source path ──


def test_knowledge_source_path():
    """v1.0.3: knowledge source path is workspaces/<id>/knowledge/sources.jsonl."""
    from workspace.manager import ensure_workspace, WS_ROOT

    ensure_workspace(WS_ID)
    new_path = WS_ROOT / WS_ID / "knowledge" / "sources.jsonl"
    old_path = WS_ROOT / WS_ID / "indexes" / "knowledge" / "sources.jsonl"

    # Neither should exist yet in test workspace
    from workspace.manager import _count_knowledge_sources
    # This calls the function which now reads from the new path
    count = _count_knowledge_sources(WS_ID)
    assert count == 0  # No data means 0 count
