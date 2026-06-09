"""Agent-supervised Tool Runtime bridge tests."""

import json


def test_capability_question_reports_tool_catalog_count(monkeypatch, tmp_path):
    import agent.llm.settings as settings_mod
    from backend.main import app
    from tool_runtime.integration import get_default_tool_runtime_client

    settings_path = tmp_path / "LLM_setting.json"
    settings_path.write_text(json.dumps({"enabled": False, "provider": "disabled"}))
    monkeypatch.setattr(settings_mod, "SETTINGS_PATH", settings_path)

    expected_count = get_default_tool_runtime_client().tool_count
    resp = app.test_client().post("/api/agent/run", json={
        "message": "你能调用多少tool",
        "workspace_id": "agent_tool_count",
    })
    data = resp.get_json()

    assert resp.status_code == 200
    assert data["intent"] == "assistant_chat"
    assert str(expected_count) in data["final_response"]
    assert "Tool Runtime" in data["final_response"]
    assert data["result"].get("tool_catalog", {}).get("count") == expected_count


def test_agent_invokes_low_risk_runtime_health_tool(monkeypatch, tmp_path):
    import agent.llm.settings as settings_mod
    from backend.main import app

    settings_path = tmp_path / "LLM_setting.json"
    settings_path.write_text(json.dumps({"enabled": False, "provider": "disabled"}))
    monkeypatch.setattr(settings_mod, "SETTINGS_PATH", settings_path)

    resp = app.test_client().post("/api/agent/run", json={
        "message": "调用 runtime.health 看一下运行时健康信息",
        "workspace_id": "agent_runtime_tool",
    })
    data = resp.get_json()

    assert resp.status_code == 200
    assert data["result"].get("mode") == "tool_runtime"
    assert data["result"].get("tool_id") == "runtime.health"
    assert data["result"].get("status") == "succeeded"
    assert "runtime.health" in data["final_response"]
    assert data["tool_invocations"][0]["tool_id"] == "runtime.health"


def test_agent_blocks_high_risk_tool_autoinvoke(monkeypatch, tmp_path):
    import agent.llm.settings as settings_mod
    from backend.main import app

    settings_path = tmp_path / "LLM_setting.json"
    settings_path.write_text(json.dumps({"enabled": False, "provider": "disabled"}))
    monkeypatch.setattr(settings_mod, "SETTINGS_PATH", settings_path)

    resp = app.test_client().post("/api/agent/run", json={
        "message": "帮我调用 command.approved_exec 执行 system.platform_info",
        "workspace_id": "agent_high_tool",
    })
    data = resp.get_json()

    assert resp.status_code == 200
    assert data["result"].get("mode") == "tool_runtime_blocked"
    assert data["result"].get("tool_id") == "command.approved_exec"
    assert data["result"].get("reason") == "approval_required"
    assert data.get("tool_invocations") == []
    assert "审批" in data["final_response"] or "approval" in data["final_response"].lower()
