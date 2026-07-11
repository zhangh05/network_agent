import asyncio


def _reset_context_runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("NA_WORKSPACE_ROOT", str(tmp_path))
    import core.context.context_store as context_store
    import core.context.unified_retriever as unified_retriever

    context_store._stores.clear()
    unified_retriever._retrievers.clear()


def test_context_store_tombstone_can_be_rebuilt_and_compacted(tmp_path, monkeypatch):
    _reset_context_runtime(tmp_path, monkeypatch)
    from core.context.context_store import get_context_store

    store = get_context_store("review_ws")
    store.put({"item_id": "same", "item_type": "knowledge_chunk", "content": "old"})
    store.delete("same")
    store.put({"item_id": "same", "item_type": "knowledge_chunk", "content": "new"})

    assert store.count("knowledge_chunk") == 1
    assert store.get("same")["content"] == "new"
    store.compact()
    assert store.count("knowledge_chunk") == 1
    assert store.get("same")["content"] == "new"


def test_knowledge_source_keeps_full_content_and_disable_hides_chunks(tmp_path, monkeypatch):
    _reset_context_runtime(tmp_path, monkeypatch)
    from agent.modules.knowledge.store import import_document, read_source, disable_source
    from core.context.unified_retriever import get_retriever

    content = "OSPF durable fact. " + ("network-body-" * 200)
    result = import_document("review_ws", "Long source", content)
    assert result["ok"] is True
    loaded = read_source("review_ws", result["source_id"])
    assert loaded["content"] == content
    assert get_retriever("review_ws").search_knowledge("OSPF", top_k=5)

    disable_source("review_ws", result["source_id"], True)
    assert get_retriever("review_ws").search_knowledge("OSPF", top_k=5) == []


def test_memory_management_search_includes_pending_records(tmp_path, monkeypatch):
    import workspace.memory_governance as governance

    monkeypatch.setattr(governance, "WS_ROOT", tmp_path)
    record = governance.MemoryRecord(
        workspace_id="review_ws",
        status="pending",
        source="agent_suggestion",
        content="BGP neighbor requires operator confirmation",
        summary="BGP neighbor review",
    )
    governance.MemoryStore()._save(record)

    results = governance.MemoryStore().search("review_ws", "BGP neighbor", limit=10)
    assert results[0]["memory_id"] == record.memory_id
    assert results[0]["status"] == "pending"


def test_memory_store_rejects_path_like_memory_ids(tmp_path, monkeypatch):
    import workspace.memory_governance as governance

    monkeypatch.setattr(governance, "WS_ROOT", tmp_path)
    store = governance.MemoryStore()
    assert store.get("review_ws", "../../escape") is None
    assert store.delete_file("review_ws", "../../escape") is False


def test_streaming_executor_preserves_mixed_read_write_order():
    from agent.llm.schemas import LLMToolCall
    from core.runtime_engine.models import SSOTRuntimeConfig
    from core.runtime_engine.query_loop import StreamingToolExecutor

    calls = []

    class Runtime:
        def invoke_raw(self, tool_id, arguments):
            calls.append((tool_id, arguments["action"]))
            return {"ok": True}

    tool_calls = [
        LLMToolCall(id="read-before", name="workspace.file", arguments={"action": "read"}),
        LLMToolCall(id="write", name="workspace.file", arguments={"action": "write"}),
        LLMToolCall(id="read-after", name="workspace.file", arguments={"action": "read"}),
    ]
    results = asyncio.run(StreamingToolExecutor(Runtime(), SSOTRuntimeConfig()).execute(tool_calls))

    assert calls == [
        ("workspace.file", "read"),
        ("workspace.file", "write"),
        ("workspace.file", "read"),
    ]
    assert [result.call_id for result in results] == ["read-before", "write", "read-after"]


def test_tracking_contract_preserves_producer_poll_arguments():
    from core.runtime_engine.tracking import normalize_tracking_payload

    tracking = normalize_tracking_payload({
        "kind": "long_task",
        "task_id": "task-1",
        "poll_action": "task_get",
        "poll_arguments": {"detail": True},
    })
    assert tracking["poll_action"] == "task_get"
    assert tracking["poll_arguments"] == {"detail": True}


def test_websocket_broadcast_is_workspace_scoped(monkeypatch):
    from backend.ws import agent_ws

    class Socket:
        def __init__(self):
            self.messages = []

        def send(self, payload):
            self.messages.append(payload)

    one = Socket()
    two = Socket()
    monkeypatch.setattr(agent_ws, "_active_ws_connections", {
        "one": ("ws_one", one),
        "two": ("ws_two", two),
    })
    agent_ws.broadcast_ws_event({
        "name": "run_status",
        "data": {"workspace_id": "ws_one", "run_id": "run-1"},
    })
    assert len(one.messages) == 1
    assert two.messages == []


def test_projected_registry_contract_has_real_module_owners():
    from registry.loader import load_capabilities, load_module_registry, load_skill_registry
    from registry.validator import validate_all

    report = validate_all(
        load_module_registry(reload=True),
        load_skill_registry(reload=True),
        load_capabilities(reload=True),
    )
    assert report.ok is True


def test_default_hook_does_not_override_destructive_approval_policy():
    from agent.hooks import HookDecision
    from agent.runtime.default_hooks import _pre_tool_use_handler

    destructive = _pre_tool_use_handler({}, {
        "tool_id": "exec.run",
        "arguments": {"command": "rm -f /tmp/example"},
    })
    code_text = _pre_tool_use_handler({}, {
        "tool_id": "workspace.file",
        "arguments": {"action": "write", "content": "subprocess.run(['echo', 'ok'])"},
    })
    secret = _pre_tool_use_handler({}, {
        "tool_id": "workspace.file",
        "arguments": {"content": 'api_key="secret-value-123"'},
    })

    assert destructive.decision != HookDecision.DENY
    assert code_text.decision != HookDecision.DENY
    assert secret.decision == HookDecision.DENY
