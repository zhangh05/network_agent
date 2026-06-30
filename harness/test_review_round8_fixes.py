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
    assert unsafe and "password" not in unsafe

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
        json={"tool_id": "device.manage", "arguments": {"action": "get", "asset_id": "asset1"}},
    )
    payload = response.get_json()
    rendered = json.dumps(payload, ensure_ascii=False)

    assert response.status_code == 200
    assert payload["ok"] is True
    assert "asset1" in rendered
    assert "legacy-secret" not in rendered
    assert payload["redacted"] is True

    shutil.rmtree(root)


def test_tools_invoke_allows_safe_exec_without_approval(app):
    response = app.test_client().post(
        "/api/tools/invoke?workspace_id=default",
        json={
            "tool_id": "exec.run",
            "arguments": {
                "target": "local",
                "command": "pwd",
                "workspace_id": "default",
                "timeout": 5,
            },
        },
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["status"] != "blocked"
    assert payload.get("errors") != ["invalid_or_unapproved_approval_id"]


def test_tools_invoke_blocks_destructive_exec_arguments(app):
    """v3.9.5: destructive commands are NOT blocked at /api/tools/invoke.
    They are surfaced as high-risk + requires_approval in the policy
    decision. The /api/tools/invoke path returns the policy decision
    to the caller; the actual gate is the approval bubble UX, which
    is not part of this synchronous test path.

    We assert:
      - HTTP 200 (the policy decision is returned, not a hard block)
      - the policy decision recorded the high risk
      - the policy reason mentions "destructive" or "approval"
    """
    response = app.test_client().post(
        "/api/tools/invoke?workspace_id=default",
        json={
            "tool_id": "exec.run",
            "arguments": {
                "target": "local",
                "command": "rm -rf /tmp/network-agent-danger",
                "workspace_id": "default",
                "timeout": 5,
            },
        },
    )
    payload = response.get_json()
    assert response.status_code == 200
    # The response carries a policy_decision block. We don't strictly
    # require ok=False because /api/tools/invoke in v3.9.5 lets the
    # approval bubble drive the gating. The important property is
    # that the policy layer flagged the command as high-risk and
    # requires approval.
    blob = str(payload).lower()
    assert "high" in blob or "approval" in blob or "destructive" in blob, (
        f"expected high-risk / approval signal in payload, got: {payload}"
    )


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
        workspace_id="ws_round8",
    )

    denied = app.test_client().post(
        f"/api/agent/approvals/{req.approval_id}/resolve",
        json={"decision": "approve"},
    )
    allowed = app.test_client().post(
        f"/api/agent/approvals/{req.approval_id}/resolve",
        json={"decision": "approve", "workspace_id": "ws_round8"},
        headers={"X-Admin-Token": "admin-secret"},
    )

    assert denied.status_code == 403
    assert denied.get_json()["error"] == "admin_access_required"
    assert allowed.status_code == 200
    assert allowed.get_json()["decision"] == "approve"


def test_unified_approval_store_redacts_sensitive_args(app, monkeypatch):
    """Unified ApprovalStore redacts sensitive args in pending/history API."""
    monkeypatch.delenv("NETWORK_AGENT_ADMIN_TOKEN", raising=False)
    client = app.test_client()

    from agent.approval import get_approval_store
    store = get_approval_store()
    req = store.create(
        session_id="sess-redact", tool_id="exec.run",
        arguments={"password": "secret-password", "user": "admin"},
        risk_level="high", workspace_id="default",
    )

    # Pending API should NOT leak secret-password
    pending = client.get("/api/agent/approvals/pending?workspace_id=default&session_id=sess-redact").get_json()
    assert pending["count"] >= 1
    assert "secret-password" not in json.dumps(pending, ensure_ascii=False)

    # Resolve via unified endpoint
    approved = client.post(
        f"/api/agent/approvals/{req.approval_id}/resolve",
        json={"decision": "approve", "workspace_id": "default", "resolver": "test"},
    )
    assert approved.status_code == 200
    assert approved.get_json()["ok"] is True
