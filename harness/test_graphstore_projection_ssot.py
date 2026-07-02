"""GraphStore projection SSOT contract tests."""

from __future__ import annotations

from types import SimpleNamespace


def test_run_and_message_projection_write_graph_events(temp_dirs):
    from core.graph.graph_store import EventType, get_graph_store, reset_graph_store
    from workspace.message_store import SessionMessageStore
    from workspace.run_store import write_run_record

    reset_graph_store()
    state = SimpleNamespace(
        request_id="run_projection_1",
        session_id="sess_projection_1",
        created_at="2026-07-02T00:00:00+00:00",
        user_input="hello",
        intent="assistant_chat",
        context={"llm": {}, "capability_id": "", "memory_written": False, "workspace_updated": False},
        active_module="",
        selected_skill="",
        runtime_mode="ssot_runtime",
        final_response="hi",
        warnings=[],
        trace_id="trace_projection_1",
        error=None,
        result_ok=True,
        result_errors=[],
        skill_results={},
        tool_results={},
    )
    rid = write_run_record(state, "default")
    store = SessionMessageStore("sess_projection_1", ws_id="default")
    msg_id = store.write_message(rid, "user", "hello")

    events = get_graph_store().get_events(rid)
    event_types = {e.event_type for e in events}
    assert EventType.RUN_RECORD_WRITTEN in event_types
    assert EventType.MESSAGE_WRITTEN in event_types
    assert msg_id == f"{rid}:user"


def test_artifact_and_memory_projection_write_graph_events(temp_dirs):
    from artifacts.store import save_artifact
    from core.graph.graph_store import EventType, get_graph_store, reset_graph_store
    from workspace.memory_governance import MemoryRecord, MemoryStore

    reset_graph_store()
    artifact = save_artifact(
        workspace_id="default",
        content="interface GigabitEthernet1/0/1",
        artifact_type="report",
        title="SSOT report",
        run_id="run_projection_2",
        session_id="sess_projection_2",
    )
    rec = MemoryRecord(
        workspace_id="default",
        session_id="sess_projection_2",
        scope="workspace",
        memory_type="operational_fact",
        status="active",
        source="user",
        content="BGP peer ASBR-PE1 belongs to WAN",
        summary="ASBR-PE1 WAN",
    )
    MemoryStore().save(rec)

    run_events = get_graph_store().get_events("run_projection_2")
    memory_events = get_graph_store().get_events(rec.memory_id)
    assert artifact is not None
    assert EventType.ARTIFACT_WRITTEN in {e.event_type for e in run_events}
    assert EventType.MEMORY_WRITTEN in {e.event_type for e in memory_events}


def test_graphstore_replay_advances_causal_clock(tmp_path):
    from core.graph.graph_store import EventType, GraphStore

    first = GraphStore(persist_dir=tmp_path)
    evt1 = first.append(EventType.RUN_STARTED, "run_replay", {})

    second = GraphStore(persist_dir=tmp_path)
    evt2 = second.append(EventType.RUN_COMPLETED, "run_replay", {})

    assert evt2.causal_index > evt1.causal_index


def test_projection_write_fails_closed_when_graphstore_unavailable(temp_dirs, monkeypatch):
    import core.graph.projection_events as projection_events
    from workspace.memory_governance import MemoryRecord, MemoryStore

    class BrokenGraphStore:
        def append(self, *_args, **_kwargs):
            raise RuntimeError("graph unavailable")

    monkeypatch.setattr(projection_events, "get_graph_store", lambda: BrokenGraphStore())

    rec = MemoryRecord(
        workspace_id="default",
        session_id="sess_projection_fail",
        scope="workspace",
        memory_type="operational_fact",
        status="active",
        source="user",
        content="this must not be projected without a graph event",
        summary="blocked projection",
    )

    try:
        MemoryStore().save(rec)
        raise AssertionError("MemoryStore.save should fail when GraphStore append fails")
    except RuntimeError as exc:
        assert "graph unavailable" in str(exc)

    assert MemoryStore().get("default", rec.memory_id) is None
