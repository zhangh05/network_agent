"""Round 8 review fixes regression tests."""

from __future__ import annotations

import base64
import json
import shutil

import pytest


@pytest.fixture()
def app(monkeypatch):
    monkeypatch.delenv("NETWORK_AGENT_AUTH_ENABLED", raising=False)
    monkeypatch.delenv("NETWORK_AGENT_API_TOKEN", raising=False)
    from backend.main import create_app

    flask_app = create_app()
    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture(autouse=True)
def reset_agent_approvals(tmp_path, monkeypatch):
    import agent.approval as approval_module
    from agent.approval import reset_approval_store_for_tests

    monkeypatch.setattr(approval_module, "_APPROVALS_FILE", tmp_path / "tool_approvals.jsonl")
    reset_approval_store_for_tests(remove_persisted=True)
    yield
    reset_approval_store_for_tests(remove_persisted=True)


def test_agent_approval_redacts_sensitive_arguments():
    from agent.approval import ApprovalRequest, ApprovalStore

    req = ApprovalRequest(
        approval_id="apr_test",
        session_id="sess_test",
        tool_id="exec.run",
        arguments={
            "command": "show version",
            "password": "secret-password",
            "nested": {"api_key": "sk-testsecretvalue123456"},
        },
        description="Run command",
        risk_level="high",
    )

    rendered = ApprovalStore._to_dict(req)
    encoded = json.dumps(rendered, ensure_ascii=False)

    assert "secret-password" not in encoded
    assert "sk-testsecretvalue123456" not in encoded
    assert rendered["arguments_preview"]["password"] == "[REDACTED]"
    assert rendered["arguments_preview"]["nested"]["api_key"] == "[REDACTED]"


def test_cmdb_tool_does_not_return_legacy_password():
    from agent.modules.cmdb.service import get_asset
    from agent.modules.cmdb.tools import tool_get_asset
    from storage.paths import workspace_root

    workspace_id = "pytest_round8_cmdb_secret"
    root = workspace_root(workspace_id)
    if root.exists():
        shutil.rmtree(root)
    cmdb_dir = root / "cmdb"
    cmdb_dir.mkdir(parents=True, exist_ok=True)
    (cmdb_dir / "assets.jsonl").write_text(
        json.dumps({
            "asset_id": "asset1",
            "name": "edge",
            "type": "router",
            "host": "192.0.2.5",
            "password": base64.b64encode(b"legacy-secret").decode("ascii"),
        }) + "\n",
        encoding="utf-8",
    )

    unsafe = get_asset(workspace_id, "asset1", safe=False)
    assert unsafe and "password" in unsafe

    result = tool_get_asset(workspace_id=workspace_id, asset_id="asset1")
    rendered = json.dumps(result, ensure_ascii=False)

    assert result["ok"] is True
    assert "legacy-secret" not in rendered
    assert "password" not in result["asset"]

    shutil.rmtree(root)


def test_tools_invoke_uses_executor_redaction_and_workspace_context(app):
    from storage.paths import workspace_root

    workspace_id = "pytest_round8_invoke_ws"
    root = workspace_root(workspace_id)
    if root.exists():
        shutil.rmtree(root)
    cmdb_dir = root / "cmdb"
    cmdb_dir.mkdir(parents=True, exist_ok=True)
    (cmdb_dir / "assets.jsonl").write_text(
        json.dumps({
            "asset_id": "asset1",
            "name": "edge",
            "type": "router",
            "host": "192.0.2.5",
            "password": "legacy-secret",
        }) + "\n",
        encoding="utf-8",
    )

    response = app.test_client().post(
        f"/api/tools/invoke?workspace_id={workspace_id}",
        json={"tool_id": "device.get", "arguments": {"asset_id": "asset1"}},
    )
    payload = response.get_json()
    rendered = json.dumps(payload, ensure_ascii=False)

    assert response.status_code == 200
    assert payload["ok"] is True
    assert "asset1" in rendered
    assert "legacy-secret" not in rendered
    assert payload["redacted"] is True

    shutil.rmtree(root)


def test_exec_run_remote_targets_are_not_blocked_by_argument_safety():
    from tool_runtime.canonical_registry import to_tool_specs
    from tool_runtime.executor import ToolInvocation
    from tool_runtime.policy import ToolPolicy

    spec = next(spec for spec, _handler in to_tool_specs() if spec.tool_id == "exec.run")
    policy = ToolPolicy()

    for target in ("ssh", "telnet"):
        decision = policy.check(
            spec,
            ToolInvocation(
                tool_id="exec.run",
                arguments={
                    "target": target,
                    "command": "show version",
                    "host": "192.0.2.1",
                    "username": "admin",
                    "password": "secret",
                },
                workspace_id="default",
                approval_id="APR-TEST",
            ),
        )
        assert decision.allowed, decision.reason


def test_destructive_routes_require_confirm(app):
    client = app.test_client()

    artifact_delete = client.delete("/api/workspaces/default/artifacts/art_missing")
    artifact_batch = client.post(
        "/api/workspaces/default/artifacts/batch-delete",
        json={"artifact_ids": ["art_missing"]},
    )
    pcap_delete = client.delete("/api/pcap/session/sess_missing?workspace_id=default")

    assert artifact_delete.status_code == 400
    assert artifact_delete.get_json()["error"] == "confirm_required"
    assert artifact_batch.status_code == 400
    assert artifact_batch.get_json()["error"] == "confirm_required"
    assert pcap_delete.status_code == 400
    assert pcap_delete.get_json()["error"] == "confirm_required"


def test_pcap_routes_validate_workspace_id(app):
    client = app.test_client()

    detail = client.get("/api/pcap/session/sess1?workspace_id=../x")
    listing = client.get("/api/pcap/sessions?workspace_id=../x")

    assert detail.status_code == 400
    assert detail.get_json()["error"] == "invalid_workspace_id"
    assert listing.status_code == 400
    assert listing.get_json()["error"] == "invalid_workspace_id"


def test_runtime_health_rejects_invalid_workspace(app):
    response = app.test_client().get("/api/runtime/health?workspace_id=../x")

    assert response.status_code == 400
    assert response.get_json()["error"] == "invalid_workspace_id"


def test_agent_approval_resolve_requires_admin_token_when_configured(monkeypatch, app):
    from agent.approval import get_approval_store

    monkeypatch.setenv("NETWORK_AGENT_ADMIN_TOKEN", "admin-secret")
    req = get_approval_store().create(
        session_id="sess_round8",
        tool_id="exec.run",
        arguments={"password": "secret"},
        description="approve",
        risk_level="high",
    )

    denied = app.test_client().post(
        f"/api/agent/approvals/{req.approval_id}/resolve",
        json={"allowed": True},
    )
    allowed = app.test_client().post(
        f"/api/agent/approvals/{req.approval_id}/resolve",
        json={"allowed": True},
        headers={"X-Admin-Token": "admin-secret"},
    )

    assert denied.status_code == 403
    assert denied.get_json()["error"] == "admin_access_required"
    assert allowed.status_code == 200
    assert allowed.get_json()["allowed"] is True


def test_runtime_tool_approval_routes_use_agent_store(app):
    client = app.test_client()

    created = client.post(
        "/api/tools/approvals",
        json={
            "workspace_id": "default",
            "tool_id": "exec.run",
            "reason": "run approved command",
            "arguments": {"password": "secret-password"},
        },
    )
    approval_id = created.get_json()["approval_id"]
    pending = client.get("/api/tools/approvals?workspace_id=default").get_json()
    approved = client.put(f"/api/tools/approvals/{approval_id}/approve")

    assert created.status_code == 200
    assert pending["count"] >= 1
    assert "secret-password" not in json.dumps(pending, ensure_ascii=False)
    assert approved.status_code == 200
    assert approved.get_json()["status"] == "approved"
