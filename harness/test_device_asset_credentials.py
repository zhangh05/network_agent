import json
import shutil


def test_cmdb_asset_password_is_resolved_only_for_internal_connectors():
    from agent.modules.cmdb.service import get_asset, list_assets, save_asset
    from agent.modules.cmdb.tools import tool_add_asset, tool_get_asset
    from storage.paths import workspace_root

    workspace_id = "pytest_asset_secret_flow"
    root = workspace_root(workspace_id)
    if root.exists():
        shutil.rmtree(root)

    result = tool_add_asset(
        workspace_id=workspace_id,
        name="edge",
        type="router",
        host="192.0.2.44",
        username="admin",
        password="secret-pass",
    )
    assert result["ok"] is True

    raw = (root / "cmdb" / "assets.jsonl").read_text(encoding="utf-8")
    assert "secret-pass" not in raw
    assert "password_secret" in raw

    safe_list = list_assets(workspace_id)
    assert "password" not in safe_list[0]
    safe_tool = tool_get_asset(workspace_id=workspace_id, asset_id=result["asset_id"])
    rendered = json.dumps(safe_tool, ensure_ascii=False)
    assert "secret-pass" not in rendered
    assert "password" not in safe_tool["asset"]

    internal = get_asset(workspace_id, result["asset_id"], safe=False)
    assert internal and internal["password"] == "secret-pass"

    if root.exists():
        shutil.rmtree(root)


def test_remote_connect_uses_cmdb_asset_id_without_frontend_password(monkeypatch):
    from agent.modules.cmdb.service import save_asset
    from agent.modules.remote import service as remote_service
    from storage.paths import workspace_root

    workspace_id = "pytest_remote_asset_secret"
    root = workspace_root(workspace_id)
    if root.exists():
        shutil.rmtree(root)
    asset = save_asset(
        workspace_id,
        {
            "name": "edge",
            "type": "router",
            "host": "192.0.2.45",
            "port": 22,
            "protocol": "ssh",
            "username": "admin",
            "password": "secret-pass",
            "vendor": "h3c",
        },
    )

    captured = {}

    class FakeSession:
        log = ["banner"]
        vendor = type("Vendor", (), {"vendor": "h3c"})()

    def fake_ssh_connect(session_id, host, port, username, password, vendor):
        captured.update({
            "session_id": session_id,
            "host": host,
            "port": port,
            "username": username,
            "password": password,
            "vendor": vendor,
        })
        return FakeSession()

    monkeypatch.setattr(remote_service, "ssh_connect", fake_ssh_connect)
    result = remote_service.connect_device(
        workspace_id=workspace_id,
        host="",
        port=22,
        protocol="ssh",
        username="",
        password="",
        vendor="",
        asset_id=asset["asset_id"],
    )

    assert result["ok"] is True
    assert captured["host"] == "192.0.2.45"
    assert captured["username"] == "admin"
    assert captured["password"] == "secret-pass"
    assert captured["vendor"] == "h3c"

    if root.exists():
        shutil.rmtree(root)


def test_remote_connect_falls_back_to_unique_cmdb_asset_when_password_empty(monkeypatch):
    from agent.modules.cmdb.service import save_asset
    from agent.modules.remote import service as remote_service
    from storage.paths import workspace_root

    workspace_id = "pytest_remote_asset_host_fallback"
    root = workspace_root(workspace_id)
    if root.exists():
        shutil.rmtree(root)
    save_asset(
        workspace_id,
        {
            "name": "edge",
            "type": "router",
            "host": "192.0.2.47",
            "port": 22,
            "protocol": "ssh",
            "username": "admin",
            "password": "secret-pass",
            "vendor": "h3c",
        },
    )

    captured = {}

    class FakeSession:
        log = ["banner"]
        vendor = type("Vendor", (), {"vendor": "h3c"})()

    def fake_ssh_connect(session_id, host, port, username, password, vendor):
        captured.update({
            "host": host,
            "port": port,
            "username": username,
            "password": password,
            "vendor": vendor,
        })
        return FakeSession()

    monkeypatch.setattr(remote_service, "ssh_connect", fake_ssh_connect)
    result = remote_service.connect_device(
        workspace_id=workspace_id,
        host="192.0.2.47",
        port=22,
        protocol="ssh",
        username="admin",
        password="",
        vendor="",
    )

    assert result["ok"] is True
    assert captured["password"] == "secret-pass"

    shutil.rmtree(root)


def test_exec_run_ssh_can_resolve_cmdb_asset_id(monkeypatch):
    from agent.modules.cmdb.service import save_asset
    from agent.modules.remote import core as remote_core
    from storage.paths import workspace_root
    from tool_runtime.canonical_registry import _handler_network_ssh
    from tool_runtime.schemas import ToolInvocation

    workspace_id = "pytest_exec_asset_secret"
    root = workspace_root(workspace_id)
    if root.exists():
        shutil.rmtree(root)
    asset = save_asset(
        workspace_id,
        {
            "name": "edge",
            "type": "router",
            "host": "192.0.2.46",
            "port": 22,
            "protocol": "ssh",
            "username": "admin",
            "password": "secret-pass",
            "vendor": "huawei",
        },
    )

    captured = {}

    class FakeSession:
        vendor = type("Vendor", (), {"vendor": "huawei"})()
        log = []

    def fake_ssh_connect(session_id, host, port, username, password, vendor):
        captured.update({
            "session_id": session_id,
            "host": host,
            "port": port,
            "username": username,
            "password": password,
            "vendor": vendor,
        })
        return FakeSession()

    monkeypatch.setattr(remote_core, "ssh_connect", fake_ssh_connect)
    monkeypatch.setattr(remote_core, "exec_command", lambda session_id, command: {"ok": True, "output": "ok"})
    monkeypatch.setattr(remote_core, "disconnect", lambda session_id: {"ok": True})

    result = _handler_network_ssh(ToolInvocation(
        tool_id="exec.run",
        workspace_id=workspace_id,
        arguments={
            "target": "ssh",
            "asset_id": asset["asset_id"],
            "command": "display version",
            "close_session": True,
        },
    ))

    assert result["ok"] is True
    assert result["output"] == "ok"
    assert captured["host"] == "192.0.2.46"
    assert captured["username"] == "admin"
    assert captured["password"] == "secret-pass"
    assert captured["vendor"] == "huawei"

    shutil.rmtree(root)


def test_runner_trim_accepts_llm_message_objects():
    from types import SimpleNamespace

    from agent.llm.schemas import LLMMessage
    from agent.runtime import runner

    old_limit = runner.MAX_MESSAGE_TURNS
    runner.MAX_MESSAGE_TURNS = 1
    try:
        state = SimpleNamespace(messages=[
            LLMMessage(role="system", content="system"),
            LLMMessage(role="user", content="one"),
            {"role": "assistant", "content": "two"},
            LLMMessage(role="user", content="three"),
            LLMMessage(role="assistant", content="four"),
        ])
        runner._trim_messages_if_needed(state)
    finally:
        runner.MAX_MESSAGE_TURNS = old_limit

    assert state.messages[0].role == "system"
    assert any(getattr(m, "role", "") == "system" for m in state.messages)


def test_memory_gate_rejects_generic_task_completion_noise():
    import shutil

    from storage.paths import workspace_root
    from workspace.memory_governance import MemoryRecord, MemoryWriteGate

    workspace_id = "pytest_memory_noise"
    root = workspace_root(workspace_id)
    if root.exists():
        shutil.rmtree(root)

    rec = MemoryRecord(
        workspace_id=workspace_id,
        memory_type="task_pattern",
        source="agent_suggestion",
        content="Task 't1' completed successfully",
        summary="Task 't1' completed successfully",
        confidence=0.9,
    )
    result = MemoryWriteGate().write(rec)

    assert result["ok"] is False
    assert result["status"] == "rejected"
    assert result["error"] == "low_value_memory"

    if root.exists():
        shutil.rmtree(root)


def test_memory_planner_does_not_write_generic_task_completion():
    from agent.runtime.memory_write.planner import MemoryWritePlanner

    ctx = type("Ctx", (), {
        "metadata": {
            "runtime_state_snapshot": {
                "task_status": "completed",
                "active_task_title": "t1",
                "active_task_id": "t1",
            }
        }
    })()

    assert MemoryWritePlanner()._from_task_completion(ctx) == []
