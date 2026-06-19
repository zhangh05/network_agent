import queue


def test_ws_done_payload_includes_full_inspector_fields(monkeypatch):
    from backend.ws import agent_ws
    import agent.app.service as service

    class FakeResult:
        def to_dict(self):
            return {
                "ok": True,
                "final_response": "answer",
                "session_id": "s-1",
                "turn_id": "t-1",
                "trace_id": "trace-1",
                "events": [
                    {"event_id": "ev-1", "type": "tool_call", "timestamp": 1.0},
                    {"event_id": "ev-2", "type": "final", "timestamp": 2.0},
                ],
                "tool_calls": [
                    {"call_id": "call-1", "tool_id": "knowledge.search", "ok": True},
                ],
                "metadata": {"source_count": 1},
                "warnings": [],
                "errors": [],
                "tool_decision": {"needed": True, "selected_tools": ["knowledge.search"]},
                "no_tool_reason": "",
            }

    class FakeApp:
        def submit_user_message(self, **_kwargs):
            return FakeResult()

    monkeypatch.setattr(service, "get_default_agent_app", lambda: FakeApp())

    event_queue = queue.Queue()
    error_holder = {"error": None}
    stats = {"live_events": 0}
    agent_ws._run_agent_thread("q", "s-1", "default", {}, event_queue, error_holder, stats)

    messages = []
    while not event_queue.empty():
        messages.append(event_queue.get())
    done = next(item for item in messages if isinstance(item, dict) and item.get("type") == "done")

    assert done["trace_id"] == "trace-1"
    assert len(done["events"]) == 2
    assert done["tool_decision"]["selected_tools"] == ["knowledge.search"]
    assert done["tool_calls"][0]["tool_id"] == "knowledge.search"
    assert done["metadata"]["stream_mode"] == "event_replay_fallback"
    assert done["metadata"]["transport"] == "websocket"
    assert error_holder["error"] is None
