import os

import pytest


@pytest.fixture()
def app(monkeypatch):
    monkeypatch.delenv("NETWORK_AGENT_AUTH_ENABLED", raising=False)
    monkeypatch.delenv("NETWORK_AGENT_API_TOKEN", raising=False)
    from backend.main import create_app

    flask_app = create_app()
    flask_app.config["TESTING"] = True
    return flask_app


def test_unsafe_api_methods_reject_foreign_origin(app):
    client = app.test_client()
    response = client.post(
        "/api/cmdb/assets",
        json={"workspace_id": "default", "name": "r1", "host": "192.0.2.10"},
        headers={"Origin": "https://evil.example"},
    )

    assert response.status_code == 403
    assert response.get_json()["error"] == "csrf_origin_denied"


def test_unsafe_api_methods_allow_local_workbench_origin(app):
    client = app.test_client()
    response = client.put(
        "/api/workspaces/pytest_csrf_dev/settings",
        json={"unknown": "ignored"},
        headers={"Origin": "http://localhost:5173"},
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "no_valid_settings"


def test_workspace_state_endpoint_matches_frontend_contract(app):
    client = app.test_client()
    response = client.get("/api/workspaces/default/state")

    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    assert isinstance(body["workspace"], dict)


def test_cmdb_invalid_workspace_and_port_return_400(app):
    client = app.test_client()

    invalid_ws = client.get("/api/cmdb/assets?workspace_id=../x")
    invalid_port = client.post(
        "/api/cmdb/assets",
        json={"workspace_id": "default", "name": "r1", "host": "192.0.2.10", "port": "bad"},
    )

    assert invalid_ws.status_code == 400
    assert invalid_ws.get_json()["error"] == "invalid_workspace_id"
    assert invalid_port.status_code == 400
    assert invalid_port.get_json()["error"] == "invalid_port"


def test_remote_invalid_workspace_and_port_return_400(app):
    client = app.test_client()

    invalid_ws = client.get("/api/remote/devices?workspace_id=../x")
    missing_sessions_ws = client.get("/api/remote/sessions")
    missing_exec_ws = client.post(
        "/api/remote/exec",
        json={"session_id": "sid", "command": "display version"},
    )
    missing_disconnect_ws = client.post(
        "/api/remote/disconnect",
        json={"session_id": "sid"},
    )
    invalid_port = client.post(
        "/api/remote/connect",
        json={"workspace_id": "default", "host": "127.0.0.1", "port": "bad"},
    )

    assert invalid_ws.status_code == 400
    assert invalid_ws.get_json()["error"] == "invalid_workspace_id"
    assert missing_sessions_ws.status_code == 400
    assert missing_sessions_ws.get_json()["error"] == "invalid_workspace_id"
    assert missing_exec_ws.status_code == 400
    assert missing_exec_ws.get_json()["error"] == "invalid_workspace_id"
    assert missing_disconnect_ws.status_code == 400
    assert missing_disconnect_ws.get_json()["error"] == "invalid_workspace_id"
    assert invalid_port.status_code == 400
    assert invalid_port.get_json()["error"] == "invalid_port"


def test_exec_run_is_not_policy_forbidden_with_approval():
    from tool_runtime.integration import get_default_tool_runtime_client
    from tool_runtime.schemas import ToolInvocation

    client = get_default_tool_runtime_client()
    spec = client._registry.get_tool("exec.run")
    decision = client._policy.check(
        spec,
        ToolInvocation(
            tool_id="exec.run",
            arguments={"command": "pwd"},
            workspace_id="default",
            approval_id="APR-TEST",
        ),
    )

    assert decision.allowed, decision.reason


def test_cmdb_export_uses_valid_csv_columns():
    from agent.modules.cmdb.service import export_assets, save_asset
    from storage.paths import workspace_root

    workspace_id = "pytest_cmdb_export"
    root = workspace_root(workspace_id)
    if root.exists():
        import shutil

        shutil.rmtree(root)

    save_result = save_asset(
        workspace_id,
        {
            "name": "edge,one",
            "type": "router",
            "host": "192.0.2.11",
            "description": "=SUM(1,1)",
            "tags": ["core", "wan"],
        },
    )
    assert save_result["ok"]

    csv_text = export_assets(workspace_id)
    rows = [line for line in csv_text.splitlines() if line]
    assert len(rows) == 2

    import csv

    parsed = list(csv.DictReader(rows))
    assert parsed[0]["name"] == "edge,one"
    assert parsed[0]["tags"] == "core;wan"
    assert parsed[0]["description"].startswith("'=SUM")
    assert parsed[0]["updated_at"]

    import shutil

    shutil.rmtree(root)


def test_device_passwords_are_stored_as_server_side_secrets_only():
    import json
    import shutil

    from agent.modules.cmdb.service import get_asset, list_assets, save_asset
    from agent.modules.remote.service import get_device_password, list_devices, save_device
    from storage.paths import workspace_root

    workspace_id = "pytest_no_passwords"
    root = workspace_root(workspace_id)
    if root.exists():
        shutil.rmtree(root)

    assert save_asset(
        workspace_id,
        {
            "name": "edge",
            "type": "router",
            "host": "192.0.2.12",
            "username": "admin",
            "password": "secret",
        },
    )["ok"]
    assert save_device(
        workspace_id,
        {
            "name": "edge",
            "host": "192.0.2.12",
            "username": "admin",
            "password": "secret",
        },
    )["ok"]

    cmdb_lines = (root / "cmdb" / "assets.jsonl").read_text(encoding="utf-8").splitlines()
    remote_lines = (root / "remote" / "connections.jsonl").read_text(encoding="utf-8").splitlines()
    cmdb_record = json.loads(cmdb_lines[-1])
    remote_record = json.loads(remote_lines[-1])

    assert "password" not in cmdb_record
    assert "password" not in remote_record
    assert "password_secret" in cmdb_record
    assert "password_secret" in remote_record
    assert "\"secret\"" not in "\n".join(cmdb_lines + remote_lines)
    assert list_assets(workspace_id)[0].get("password") is None
    assert list_devices(workspace_id)[0].get("password") is None
    unsafe = get_asset(workspace_id, cmdb_record["asset_id"], safe=False)
    assert unsafe and unsafe["password"] == "secret"
    assert get_device_password(workspace_id, remote_record["device_id"]) == "secret"

    shutil.rmtree(root)


def test_workspace_delete_requires_explicit_confirm(app):
    client = app.test_client()

    response = client.delete("/api/workspaces/scratch")

    assert response.status_code == 400
    assert response.get_json()["error"] == "confirm_required"
