"""Platform Runtime Closure v0.2 completion tests."""

import json
import os
import pytest

# Disable rate limiter during tests
os.environ["RATE_LIMIT_DISABLED"] = "1"


def test_run_history_endpoints_are_workspace_backed_and_safe():
    from backend.main import app
    from agent.state import NetworkAgentState
    from workspace.run_store import write_run_record

    ws_id = "closure_v02_ws"
    state = NetworkAgentState(
        user_input="你好 password supersecret token=abc123",
        intent="assistant_chat",
        active_module="assistant",
        selected_skill="none",
        workspace_id=ws_id,
    )
    state.final_response = "你好，我是 Network Agent"
    state.context["capability_id"] = "assistant.chat"
    state.trace_id = "trace_v02"
    state.skill_results = {"ok": True, "quality_summary": {
        "source_residue_count": 0,
        "silent_drop_count": 0,
        "unsupported_count": 0,
        "safe_drop_count": 0,
        "review_required_count": 0,
        "source_residue_items": ["must not persist"],
    }}
    run_id = write_run_record(state, ws_id)

    client = app.test_client()
    for path in (
        f"/api/runs/{run_id}?workspace_id={ws_id}",
        f"/api/workspaces/{ws_id}/runs/{run_id}",
    ):
        resp = client.get(path)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["run_id"] == run_id
        serialized = json.dumps(data, ensure_ascii=False)
        assert "supersecret" not in serialized
        assert "abc123" not in serialized
        assert "source_config" not in data
        assert "deployable_config" not in data
        assert "prompt" not in data
        assert "safe_context" not in data
        assert "source_residue_items" not in serialized

    history = client.get(f"/api/workspaces/{ws_id}/history?limit=5").get_json()
    assert history["workspace_id"] == ws_id
    assert any(r["run_id"] == run_id for r in history["runs"])

    recent = client.get(f"/api/runs/recent?workspace_id={ws_id}&limit=5").get_json()
    assert any(r["run_id"] == run_id for r in recent["runs"])


def test_tool_runtime_client_appends_safe_trace_metadata():
    from agent.state import NetworkAgentState
    from observability.trace import create_trace, finalize_trace
    from observability.store import write_trace, get_trace
    from tool_runtime.context import ToolRuntimeContext
    from tool_runtime.integration import get_default_tool_runtime_client

    ws_id = "tool_trace_v02_ws"
    state = NetworkAgentState(user_input="trace", intent="assistant_chat", workspace_id=ws_id)
    trace_id = create_trace(state, ws_id)
    write_trace(finalize_trace(state, ws_id), ws_id)

    ctx = ToolRuntimeContext(
        workspace_id=ws_id,
        run_id=state.request_id,
        trace_id=trace_id,
        job_id="job_1",
        capability="config.translate",
        skill="config_translation",
        module="config_translation",
    )
    result = get_default_tool_runtime_client().invoke(
        "command.dry_run_echo",
        {"msg": "hello", "password": "secret123"},
        dry_run=True,
        context=ctx,
    )
    assert result.status == "dry_run"

    trace = get_trace(state.request_id, ws_id)
    tool_events = [e for e in trace["events"] if e.get("event_type") == "tool_runtime"]
    assert tool_events
    event = tool_events[-1]
    meta = event["metadata"]
    allowed = {
        "invocation_id", "tool_id", "status", "duration_ms", "dry_run",
        "redacted", "policy_allowed", "policy_reason", "risk_level",
        "artifact_ids", "workspace_id", "run_id", "job_id", "capability",
        "skill", "module",
    }
    assert set(meta).issubset(allowed)
    serialized = json.dumps(event, ensure_ascii=False)
    assert "secret123" not in serialized
    assert "arguments" not in serialized
    assert "output" not in serialized
    assert meta["tool_id"] == "command.dry_run_echo"
    assert meta["workspace_id"] == ws_id


def test_frontend_localstorage_not_history_or_secret_store():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    html = open(os.path.join(root, "frontend", "index.html"), encoding="utf-8").read()

    assert "run_history" not in html
    assert "recent_runs" not in html
    assert "localStorage.setItem('na_history" not in html
    assert "localStorage.setItem('na_runs" not in html
    assert "llm_key:" not in html
    assert "llm_sys:" not in html
    assert "/api/agent/llm/config" in html
    assert "payload.api_key" in html  # sent to backend only when user enters new key
    assert "localStorage.setItem('na_settings',JSON.stringify(uiCfg))" in html


def test_memory_page_loads_backend_memory_store():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    html = open(os.path.join(root, "frontend", "index.html"), encoding="utf-8").read()

    assert "function loadMemoryPage()" in html
    assert "if(name==='memory') loadMemoryPage();" in html
    assert "/api/memory/status" in html
    assert "/api/memory/list?limit=100" in html
    assert "mem-list" in html


def test_llm_config_save_api_persists_for_backend_runtime(monkeypatch, tmp_path):
    import agent.llm.settings as settings_mod
    from backend.main import app

    settings_path = tmp_path / "LLM_setting.json"
    monkeypatch.setattr(settings_mod, "SETTINGS_PATH", settings_path)

    payload = {
        "enabled": True,
        "provider": "minimax",
        "base_url": "https://api.minimax.chat/v1",
        "api_key": "sk-ui-saved-12345678",
        "model": "MiniMax-M3",
        "temperature": 0.2,
        "max_tokens": 1200,
    }
    resp = app.test_client().post("/api/agent/llm/config", json=payload)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert "sk-ui-saved-12345678" not in json.dumps(data, ensure_ascii=False)
    assert data["config"]["key_configured"] is True

    from agent.llm.config import resolve_provider_config
    cfg = resolve_provider_config()
    assert cfg["config_source"] == "ui_settings"
    assert cfg["enabled"] is True
    assert cfg["provider"] == "minimax"
    assert cfg["model"] == "MiniMax-M3"
    assert cfg["api_key"] == "sk-ui-saved-12345678"


def test_required_agent_conversation_inputs_via_http_api():
    from backend.main import app

    client = app.test_client()
    inputs = [
        "你好",
        "你是谁",
        "你能做什么",
        "manual_review 是什么",
        "quality_summary 是什么",
        "source_residue 是什么",
        "silent_drop 是什么",
        "帮我画拓扑",
        "帮我巡检",
    ]
    for msg in inputs:
        resp = client.post("/api/agent/run", json={
            "message": msg,
            "workspace_id": "closure_chat_v02",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        text = data.get("final_response") or ""
        assert "I didn't understand your request" not in text
        serialized = json.dumps(data, ensure_ascii=False)
        assert "deployable_config" not in serialized
        assert data.get("artifact_refs") == []
        assert data.get("job_refs") == []
        assert data.get("report_refs") == []

        if msg in ("你好", "你是谁", "你能做什么"):
            assert data["intent"] == "assistant_chat"
            assert data["active_module"] == "assistant"
            assert data["selected_skill"] == "assistant_chat"
            assert not any("coming_soon" in w for w in data.get("warnings", []))
        if msg in ("帮我画拓扑", "帮我巡检"):
            assert data["ok"] is False
            assert "coming soon" in text.lower() or "coming_soon" in serialized


def test_agent_model_question_is_basic_assistant_chat(monkeypatch, tmp_path):
    import agent.llm.settings as settings_mod
    from backend.main import app
    settings_path = tmp_path / "LLM_setting.json"
    settings_path.write_text(json.dumps({
        "enabled": False,
        "provider": "disabled",
        "safe_mode": True,
    }))
    monkeypatch.setattr(settings_mod, "SETTINGS_PATH", settings_path)

    resp = app.test_client().post("/api/agent/run", json={
        "message": "你是什么模型",
        "workspace_id": "closure_model_chat",
    })
    data = resp.get_json()
    assert data["intent"] == "assistant_chat"
    assert data["active_module"] == "assistant"
    assert data["selected_skill"] == "assistant_chat"
    assert data["llm"]["used"] is False
    assert "Network Agent" in data["final_response"]
    assert "人工复核" not in data["final_response"]
    assert "翻译结果" not in data["final_response"]


def test_assistant_chat_stays_deterministic_when_llm_configured(monkeypatch, tmp_path):
    import agent.llm.settings as settings_mod
    from backend.main import app

    settings_path = tmp_path / "LLM_setting.json"
    settings_path.write_text(json.dumps({
        "enabled": True,
        "provider": "minimax",
        "base_url": "https://api.minimaxi.com/v1",
        "api_key": "sk-test-configured-12345678",
        "model": "MiniMax-M3",
    }))
    monkeypatch.setattr(settings_mod, "SETTINGS_PATH", settings_path)

    resp = app.test_client().post("/api/agent/run", json={
        "message": "你好",
        "workspace_id": "closure_chat_llm_configured",
    })
    data = resp.get_json()
    assert data["intent"] == "assistant_chat"
    assert data["active_module"] == "assistant"
    # v0.6: assistant_chat defaults to with-tools; LLM is attempted when configured
    # llm.used tracks whether an LLM call was attempted (not whether it succeeded)
    assert data["llm"]["used"] is True
    assert "I didn't understand" not in data["final_response"]
    assert "<think>" not in data["final_response"].lower()


def test_quality_summary_residue_promotes_warning_and_manual_review():
    from backend.main import app

    cfg = "interface GigabitEthernet0/0\n ip address 10.1.1.1 255.255.255.0\n!"
    resp = app.test_client().post("/api/agent/run", json={
        "message": "翻译配置",
        "workspace_id": "closure_quality_v02",
        "payload": {
            "source_config": cfg,
            "source_vendor": "cisco",
            "target_vendor": "huawei",
        },
    })
    assert resp.status_code == 200
    data = resp.get_json()
    qs = data["quality_summary"]
    assert qs["source_residue_count"] > 0
    assert data["warnings"]
    assert data["manual_review_count"] > 0
    manual = data["result"]["manual_review"]
    assert any(item.get("risk_level") == "high" for item in manual)
    assert "completed successfully" not in data["final_response"].lower()


def test_report_summary_contains_quality_summary_counts():
    from reports_engine.renderer import render_config_translation_report

    agent_result = {
        "trace_id": "trace_qs",
        "runtime_mode": "fallback",
        "result": {
            "deployable_config": "",
            "manual_review": [],
            "semantic_near": [],
            "unsupported": [],
            "translator_entry": "translate_bundle",
            "quality_summary": {
                "source_residue_count": 2,
                "silent_drop_count": 1,
                "unsupported_count": 0,
                "safe_drop_count": 3,
                "review_required_count": 2,
            },
        },
    }
    doc = render_config_translation_report("closure_report_v02", "run_qs", agent_result)
    assert "quality_summary residue=2" in doc.summary
    assert doc.metadata["quality_summary"]["silent_drop_count"] == 1
    assert any(section.section_id == "quality_summary" for section in doc.sections)
