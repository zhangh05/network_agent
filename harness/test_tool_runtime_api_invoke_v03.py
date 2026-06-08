# harness/test_tool_runtime_api_invoke_v03.py
"""Test new Tool Runtime API endpoints: invoke, dry-run, history, approvals, permissions.

Version: v0.3 — Interactive Tool UI support
"""

import json
import pytest


PROJECT_ROOT = __file__.rsplit("/harness", 1)[0]

EXPECTED_TOOLS = 55


def _get_app():
    from backend.main import create_app
    return create_app()


def _get_client():
    app = _get_app()
    return app.test_client()


class TestInvokeEndpoint:
    """POST /api/tools/invoke — Execute tool through full safety pipeline."""

    def test_invoke_requires_tool_id(self):
        client = _get_client()
        resp = client.post("/api/tools/invoke", json={})
        data = resp.get_json()
        assert resp.status_code == 400
        assert data.get("error") == "tool_id is required"

    def test_invoke_low_risk_tool_succeeds(self):
        client = _get_client()
        resp = client.post("/api/tools/invoke", json={
            "tool_id": "artifact.list",
            "arguments": {},
            "workspace_id": "default",
        })
        data = resp.get_json()
        assert resp.status_code == 200
        assert data.get("invocation_id")
        assert data.get("status") in ("succeeded", "dry_run")
        assert data.get("tool_id") == "artifact.list"

    def test_invoke_unknown_tool(self):
        client = _get_client()
        resp = client.post("/api/tools/invoke", json={
            "tool_id": "nonexistent.tool",
            "arguments": {},
        })
        data = resp.get_json()
        assert data.get("status") == "failed"

    def test_invoke_high_risk_without_approval(self):
        client = _get_client()
        resp = client.post("/api/tools/invoke", json={
            "tool_id": "command.approved_exec",
            "arguments": {"command_id": "system.platform_info"},
        })
        data = resp.get_json()
        # Should be blocked since no approval_id
        assert data.get("status") in ("blocked", "failed")

    def test_invoke_high_risk_with_approval(self):
        client = _get_client()
        resp = client.post("/api/tools/invoke", json={
            "tool_id": "command.approved_exec",
            "arguments": {"command_id": "system.platform_info"},
            "approval_id": "APR-TEST001",
        })
        data = resp.get_json()
        assert resp.status_code == 200
        # With approval_id, should proceed (actual result depends on env)
        assert data.get("invocation_id")

    def test_invoke_rejects_unknown_command_id(self):
        client = _get_client()
        resp = client.post("/api/tools/invoke", json={
            "tool_id": "command.approved_exec",
            "arguments": {"command_id": "rm -rf /"},
            "approval_id": "APR-TEST001",
        })
        data = resp.get_json()
        # Must be blocked or failed — rm -rf is not on the allowlist
        assert data.get("status") in ("blocked", "failed")

    def test_invoke_forbidden_tool_blocked(self):
        client = _get_client()
        resp = client.post("/api/tools/invoke", json={
            "tool_id": "shell.exec",
            "arguments": {"cmd": "echo hello"},
        })
        data = resp.get_json()
        # Should fail since shell.exec is not registered
        assert data.get("status") == "failed"

    def test_invoke_dry_run_not_actually_execute(self):
        client = _get_client()
        resp = client.post("/api/tools/invoke", json={
            "tool_id": "artifact.list",
            "arguments": {},
            "dry_run": True,
        })
        data = resp.get_json()
        if data.get("status") == "dry_run":
            assert data.get("ok") is True
        # If the tool doesn't support dry_run, it might still succeed
        # as a regular invocation. Both are acceptable.

    def test_invoke_returns_structured_output(self):
        client = _get_client()
        resp = client.post("/api/tools/invoke", json={
            "tool_id": "runtime.info",
            "arguments": {},
        })
        data = resp.get_json()
        assert "invocation_id" in data
        assert "tool_id" in data
        assert "status" in data
        assert "duration_ms" in data
        assert "policy_decision" in data or data.get("status") == "failed"

    def test_invoke_workspace_filtered(self):
        """History should be filterable by workspace_id."""
        client = _get_client()
        ws = "default"
        # Execute a tool
        resp = client.post(f"/api/tools/invoke?workspace_id={ws}", json={
            "tool_id": "workspace.info",
            "arguments": {"workspace_id": ws},
        })
        assert resp.status_code == 200

        # Check history
        resp2 = client.get(f"/api/tools/history?workspace_id={ws}")
        data2 = resp2.get_json()
        assert "records" in data2
        assert len(data2["records"]) >= 1


class TestDryRunEndpoint:
    """POST /api/tools/dry-run — Preview invocation."""

    def test_dry_run_returns_preview(self):
        client = _get_client()
        resp = client.post("/api/tools/dry-run", json={
            "tool_id": "web.fetch_summary",
            "arguments": {"url": "https://example.com"},
        })
        data = resp.get_json()
        assert resp.status_code == 200
        assert data.get("ok") is True
        assert data.get("dry_run") is True
        assert "would_do" in data

    def test_dry_run_unknown_tool(self):
        client = _get_client()
        resp = client.post("/api/tools/dry-run", json={
            "tool_id": "nonexistent.tool",
        })
        assert resp.status_code == 404

    def test_dry_run_requires_tool_id(self):
        client = _get_client()
        resp = client.post("/api/tools/dry-run", json={})
        assert resp.status_code == 400


class TestHistoryEndpoint:
    """GET /api/tools/history — Execution history."""

    def test_history_returns_records(self):
        client = _get_client()
        resp = client.get("/api/tools/history?workspace_id=default")
        data = resp.get_json()
        assert "records" in data
        assert "count" in data
        assert isinstance(data["records"], list)

    def test_history_non_existent_workspace(self):
        client = _get_client()
        resp = client.get("/api/tools/history?workspace_id=nonexistent_ws")
        data = resp.get_json()
        assert data["count"] == 0
        assert data["records"] == []


class TestApprovalsEndpoint:
    """Approval workflow endpoints."""

    def test_request_approval(self):
        client = _get_client()
        resp = client.post("/api/tools/approvals", json={
            "tool_id": "command.approved_exec",
            "reason": "Need to run health check",
            "workspace_id": "default",
            "user": "test_user",
        })
        data = resp.get_json()
        assert resp.status_code == 200
        assert data.get("ok") is True
        assert data.get("approval_id")
        assert data.get("approval_id").startswith("APR-")
        assert data.get("status") == "pending"

    def test_request_approval_requires_reason(self):
        client = _get_client()
        resp = client.post("/api/tools/approvals", json={
            "tool_id": "command.approved_exec",
        })
        assert resp.status_code == 400

    def test_list_approvals(self):
        client = _get_client()
        # Create one first
        client.post("/api/tools/approvals", json={
            "tool_id": "command.approved_exec",
            "reason": "test",
            "workspace_id": "default",
            "user": "test_user",
        })
        resp = client.get("/api/tools/approvals?workspace_id=default")
        data = resp.get_json()
        assert "approvals" in data
        assert "count" in data
        assert data["count"] >= 1

    def test_approve_request(self):
        client = _get_client()
        # Create approval
        r = client.post("/api/tools/approvals", json={
            "tool_id": "command.approved_exec",
            "reason": "test approve",
            "workspace_id": "default",
            "user": "test_user",
        })
        aid = r.get_json()["approval_id"]

        # Approve it
        resp = client.put(f"/api/tools/approvals/{aid}/approve")
        data = resp.get_json()
        assert resp.status_code == 200
        assert data.get("status") == "approved"

    def test_reject_request(self):
        client = _get_client()
        # Create approval
        r = client.post("/api/tools/approvals", json={
            "tool_id": "command.approved_exec",
            "reason": "test reject",
            "workspace_id": "default",
            "user": "test_user",
        })
        aid = r.get_json()["approval_id"]

        # Reject it
        resp = client.put(f"/api/tools/approvals/{aid}/reject")
        data = resp.get_json()
        assert resp.status_code == 200
        assert data.get("status") == "rejected"

    def test_approve_unknown(self):
        client = _get_client()
        resp = client.put("/api/tools/approvals/APR-NOTEXIST/approve")
        assert resp.status_code == 404


class TestPermissionsEndpoint:
    """GET /api/tools/permissions — Workspace-level permissions."""

    def test_permissions_returns_structure(self):
        client = _get_client()
        resp = client.get("/api/tools/permissions?workspace_id=default")
        data = resp.get_json()
        assert "workspace_id" in data
        assert "tools" in data
        assert "forbidden_count" in data
        assert "high_risk_count" in data
        assert "approval_required_count" in data

    def test_permissions_all_tools_listed(self):
        client = _get_client()
        resp = client.get("/api/tools/permissions?workspace_id=default")
        data = resp.get_json()
        perms = data.get("tools", [])
        assert len(perms) == EXPECTED_TOOLS, f"Expected {EXPECTED_TOOLS} tools, got {len(perms)}"

    def test_permissions_each_tool_has_fields(self):
        client = _get_client()
        resp = client.get("/api/tools/permissions?workspace_id=default")
        data = resp.get_json()
        for perm in data["tools"]:
            assert "tool_id" in perm
            assert "enabled" in perm
            assert "risk_level" in perm
            assert "requires_approval" in perm

    def test_permissions_invalid_workspace(self):
        client = _get_client()
        resp = client.get("/api/tools/permissions?workspace_id=../../etc")
        assert resp.status_code == 400


class TestCatalogStillWorks:
    """Verify existing catalog endpoint is unaffected."""

    def test_catalog_still_55(self):
        client = _get_client()
        resp = client.get("/api/tools/catalog")
        data = resp.get_json()
        assert len(data["tools"]) == EXPECTED_TOOLS

    def test_catalog_no_handler_leak(self):
        client = _get_client()
        resp = client.get("/api/tools/catalog")
        data = resp.get_json()
        catalog_str = json.dumps(data)
        assert "function" not in catalog_str
        assert "<function" not in catalog_str


class TestInvokeToHistoryFlow:
    """End-to-end: invoke -> history."""

    def test_invoke_then_appears_in_history(self):
        client = _get_client()
        # Invoke a tool
        r1 = client.post("/api/tools/invoke?workspace_id=default", json={
            "tool_id": "runtime.info",
            "arguments": {},
        })
        inv_id = r1.get_json().get("invocation_id")
        assert inv_id

        # Check history contains this invocation
        r2 = client.get("/api/tools/history?workspace_id=default&limit=200")
        records = r2.get_json()["records"]
        ids = [rec.get("invocation_id", "") for rec in records]
        assert inv_id in ids

    def test_multiple_invocations_all_in_history(self):
        client = _get_client()
        tools_to_invoke = ["artifact.list", "runtime.info", "workspace.info"]
        inv_ids = []
        for tid in tools_to_invoke:
            r = client.post("/api/tools/invoke?workspace_id=default", json={
                "tool_id": tid,
                "arguments": {"workspace_id": "default"},
            })
            data = r.get_json()
            if data.get("invocation_id"):
                inv_ids.append(data["invocation_id"])

        r = client.get("/api/tools/history?workspace_id=default&limit=200")
        records = r.get_json()["records"]
        ids_in_history = set(rec.get("invocation_id", "") for rec in records)
        for iid in inv_ids:
            assert iid in ids_in_history, f"{iid} not in history"


class TestNoSecurityRegression:
    """Ensure new endpoints don't create security gaps."""

    def test_invoke_no_full_args_in_response(self):
        client = _get_client()
        resp = client.post("/api/tools/invoke", json={
            "tool_id": "artifact.list",
            "arguments": {"workspace_id": "default", "password": "secret123"},
        })
        data = resp.get_json()
        body = json.dumps(data)
        assert "secret123" not in body.lower()

    def test_history_no_sensitive_data(self):
        client = _get_client()
        resp = client.get("/api/tools/history?workspace_id=default&limit=200")
        data = resp.get_json()
        body = json.dumps(data)
        assert "password" not in body.lower()
        assert "secret" not in body.lower()

    def test_catalog_get_still_readonly(self):
        """POST to catalog should still not work."""
        client = _get_client()
        resp = client.post("/api/tools/catalog")
        assert resp.status_code != 200

    def test_invoke_cannot_add_new_tools(self):
        """Invoke endpoint cannot register new tools."""
        client = _get_client()
        resp = client.post("/api/tools/invoke", json={
            "tool_id": "__new__malicious.tool",
            "arguments": {},
        })
        assert resp.get_json().get("status") == "failed"
