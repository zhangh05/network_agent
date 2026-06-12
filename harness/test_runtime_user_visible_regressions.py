"""User-visible runtime regressions for LLM status, chat history, and audit."""

from types import SimpleNamespace
import json


def test_llm_status_connected_requires_chat_completion_ok(monkeypatch):
    from agent.llm.config import get_llm_status

    monkeypatch.setattr("agent.llm.config.load_llm_config", lambda: {})
    monkeypatch.setattr(
        "agent.llm.config.resolve_provider_config",
        lambda _cfg: {
            "enabled": True,
            "provider": "minimax",
            "provider_type": "openai_compatible",
            "model": "MiniMax-M3",
            "key_loaded": True,
            "key_source": "ui_settings",
            "config_source": "ui_settings",
        },
    )
    monkeypatch.setattr(
        "agent.llm.config._provider_health",
        lambda _provider: {
            "configured": True,
            "key_loaded": True,
            "connected": False,
            "chat_completion_ok": False,
            "chat_completion_endpoint_reachable": False,
            "http_status": 404,
            "last_error": "HTTP Error 404",
        },
    )

    status = get_llm_status()

    assert status["key_loaded"] is True
    assert status["connected"] is False
    assert status["health"]["http_status"] == 404


def test_provider_health_clears_base_url_error_when_chat_completion_succeeds(monkeypatch):
    import urllib.error
    from unittest.mock import MagicMock
    from agent.llm.provider import health

    cfg = {
        "enabled": True,
        "provider": "minimax",
        "provider_type": "openai_compatible",
        "api_key": "sk-test",
        "base_url": "https://api.example/v1",
        "model": "MiniMax-M3",
    }
    http_404 = urllib.error.HTTPError(
        "https://api.example/v1",
        404,
        "Not Found",
        {},
        None,
    )
    ok_response = MagicMock()
    ok_response.status = 200
    ok_response.__enter__ = MagicMock(return_value=ok_response)
    ok_response.__exit__ = MagicMock(return_value=False)

    def fake_urlopen(req, timeout=0):
        url = req.get_full_url()
        if url.rstrip("/") == "https://api.example/v1":
            raise http_404
        return ok_response

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = health(cfg)

    assert result["connected"] is True
    assert result["chat_completion_ok"] is True
    assert result["chat_completion_endpoint_reachable"] is True
    assert result["http_status"] == 200
    assert result["last_error"] is None


def test_session_message_store_sanitizes_assistant_reasoning(tmp_path, monkeypatch):
    import workspace.manager as manager
    import workspace.message_store as message_store

    monkeypatch.setattr(manager, "WS_ROOT", tmp_path)
    monkeypatch.setattr(message_store, "WS_ROOT", tmp_path)

    store = message_store.SessionMessageStore("session_reasoning", ws_id="default")
    msg_id = store.write_message(
        "run_reasoning",
        "assistant",
        "<think>private chain</think>\n最终回答",
        metadata={"created_at": "2026-06-12T00:00:00Z"},
    )

    assert msg_id == "run_reasoning:assistant"
    messages = store.get_messages()
    assert messages[0]["content"] == "最终回答"
    assert "<think>" not in messages[0]["content"].lower()
    assert "private chain" not in messages[0]["content"]


def test_session_message_store_orders_user_before_assistant_for_same_run(tmp_path, monkeypatch):
    import workspace.manager as manager
    import workspace.message_store as message_store

    monkeypatch.setattr(manager, "WS_ROOT", tmp_path)
    monkeypatch.setattr(message_store, "WS_ROOT", tmp_path)

    store = message_store.SessionMessageStore("session_order", ws_id="default")
    msg_dir = store._messages_dir()
    msg_dir.mkdir(parents=True, exist_ok=True)
    (msg_dir / "run_1:assistant.json").write_text(json.dumps({
        "role": "assistant",
        "run_id": "run_1",
        "session_id": "session_order",
        "content": "answer",
        "metadata": {"created_at": ""},
    }))
    (msg_dir / "run_1:user.json").write_text(json.dumps({
        "role": "user",
        "run_id": "run_1",
        "session_id": "session_order",
        "content": "question",
        "metadata": {"created_at": ""},
    }))

    messages = store.get_messages()

    assert [m["role"] for m in messages] == ["user", "assistant"]


def test_runtime_persisted_run_has_created_at_when_context_metadata_empty(tmp_path, monkeypatch):
    import workspace.manager as manager
    import workspace.message_store as message_store
    import workspace.run_store as run_store
    import workspace.session_store as session_store
    from agent.core.session import AgentSession
    from agent.core.turn import AgentTurn
    from agent.protocol.op import AgentOp
    from agent.runtime.loop import _persist_run_record
    from agent.runtime.result import AgentResult

    for module in (manager, message_store, run_store, session_store):
        monkeypatch.setattr(module, "WS_ROOT", tmp_path)

    op = AgentOp.user_message("hello", session_id="session_recent", workspace_id="default")
    op.created_at = ""
    turn = AgentTurn.from_op(op)
    turn.turn_id = "run_recent_created_at"
    session = AgentSession(session_id="session_recent", workspace_id="default")
    result = AgentResult(ok=False, final_response="failed", errors=["timeout"])
    context = SimpleNamespace(metadata={}, module_snapshot={}, skill_snapshot={})

    _persist_run_record(session, turn, result, context)

    record = run_store.get_run("run_recent_created_at", "default")
    assert record["created_at"]
    assert record["started_at"] == record["created_at"]


def test_runtime_persisted_run_projects_selected_skill_from_metadata(tmp_path, monkeypatch):
    import workspace.manager as manager
    import workspace.message_store as message_store
    import workspace.run_store as run_store
    import workspace.session_store as session_store
    from agent.core.session import AgentSession
    from agent.core.turn import AgentTurn
    from agent.protocol.op import AgentOp
    from agent.runtime.loop import _persist_run_record
    from agent.runtime.result import AgentResult

    for module in (manager, message_store, run_store, session_store):
        monkeypatch.setattr(module, "WS_ROOT", tmp_path)

    op = AgentOp.user_message("translate this config", session_id="session_skill", workspace_id="default")
    turn = AgentTurn.from_op(op)
    turn.turn_id = "run_selected_skill"
    session = AgentSession(session_id="session_skill", workspace_id="default")
    result = AgentResult(ok=True, final_response="done")
    context = SimpleNamespace(
        metadata={
            "selected_skills": ["assistant_chat", "config_translation"],
            "visible_tools": ["config_translation.translate_config"],
        },
        module_snapshot={},
        skill_snapshot={},
    )

    _persist_run_record(session, turn, result, context)

    record = run_store.get_run("run_selected_skill", "default")
    assert record["selected_skill"] == "config_translation"
    assert record["active_module"] == "config_translation"


def test_list_runs_sorts_by_created_at_before_limiting(tmp_path, monkeypatch):
    import workspace.manager as manager
    import workspace.run_store as run_store

    monkeypatch.setattr(manager, "WS_ROOT", tmp_path)
    monkeypatch.setattr(run_store, "WS_ROOT", tmp_path)

    runs_dir = tmp_path / "default" / "runs"
    runs_dir.mkdir(parents=True)
    (runs_dir / "z_old.json").write_text(json.dumps({
        "run_id": "z_old",
        "created_at": "2026-06-01T00:00:00+00:00",
    }))
    (runs_dir / "a_new.json").write_text(json.dumps({
        "run_id": "a_new",
        "created_at": "2026-06-12T00:00:00+00:00",
    }))
    (runs_dir / "m_backfill.json").write_text(json.dumps({
        "run_id": "m_backfill",
        "created_at": "",
        "finished_at": "2026-06-13T00:00:00",
    }))

    runs = run_store.list_runs("default", limit=2)

    assert [r["run_id"] for r in runs] == ["m_backfill", "a_new"]
    assert runs[0]["created_at"] == "2026-06-13T00:00:00"


def test_list_runs_sorts_mixed_timezone_timestamps_by_instant(tmp_path, monkeypatch):
    import workspace.manager as manager
    import workspace.run_store as run_store

    monkeypatch.setattr(manager, "WS_ROOT", tmp_path)
    monkeypatch.setattr(run_store, "WS_ROOT", tmp_path)

    runs_dir = tmp_path / "default" / "runs"
    runs_dir.mkdir(parents=True)
    (runs_dir / "old_failure.json").write_text(json.dumps({
        "run_id": "old_failure",
        "created_at": "2026-06-12T10:16:40+08:00",
        "status": "error",
    }))
    (runs_dir / "new_success.json").write_text(json.dumps({
        "run_id": "new_success",
        "created_at": "2026-06-12T02:31:13+00:00",
        "status": "ok",
    }))

    runs = run_store.list_runs("default", limit=2)

    assert [r["run_id"] for r in runs] == ["new_success", "old_failure"]


def test_runtime_prompt_defaults_to_quick_answer_shape():
    from agent.runtime.prompts import build_system_prompt

    prompt = build_system_prompt()

    assert "3-5" in prompt
    assert "展开排查步骤" in prompt


def test_tool_registry_dispatch_uses_tool_runtime_invoke():
    from agent.tools.registry import ToolRegistry

    class FakeResult:
        status = "succeeded"
        summary = "health ok"
        errors = []
        warnings = []
        output = {"ok": True}

        def as_dict(self):
            return {
                "tool_id": "runtime.health",
                "status": self.status,
                "summary": self.summary,
                "errors": self.errors,
                "warnings": self.warnings,
            }

    class FakeClient:
        def __init__(self):
            self.calls = []

        def invoke(self, tool_id, args, context=None):
            self.calls.append((tool_id, args, context))
            return FakeResult()

    client = FakeClient()
    registry = ToolRegistry()
    registry._tool_client = client

    result = registry.dispatch("runtime.health", {"check": "all"}, context="ctx")

    assert client.calls == [("runtime.health", {"check": "all"}, "ctx")]
    assert result["ok"] is True
    assert result["summary"] == "health ok"
