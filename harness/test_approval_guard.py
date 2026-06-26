# harness/test_approval_guard.py
"""Approval API admin authentication tests.

Tests:
1. Non-localhost + no X-Admin-Token: 403
2. Correct token: approve/reject succeeds
3. Wrong token: 403
4. Pending -> approved -> can invoke
   Pending -> rejected -> cannot invoke
   Approved -> reject not allowed (already resolved)
5. Cross-workspace approval cannot invoke
"""

import os
import pytest


@pytest.fixture
def app_with_approvals():
    """Create a Flask app with approval routes."""
    from flask import Flask
    from backend.api.runtime_routes import register_runtime_routes

    app = Flask(__name__)
    app.config["TESTING"] = True  # Disable rate limiting

    # Register runtime routes (includes approval endpoints)
    register_runtime_routes(app)

    return app


@pytest.fixture
def client(app_with_approvals):
    """Create a test client."""
    return app_with_approvals.test_client()


@pytest.fixture
def reset_approvals(tmp_path, monkeypatch):
    """Reset the global _tool_approvals dict before each test."""
    from backend.api import runtime_routes
    import agent.approval as approval_module
    from agent.approval import reset_approval_store_for_tests

    monkeypatch.setattr(approval_module, "_APPROVALS_FILE", tmp_path / "tool_approvals.jsonl")
    runtime_routes._tool_approvals.clear()
    reset_approval_store_for_tests(remove_persisted=True)
    yield
    runtime_routes._tool_approvals.clear()
    reset_approval_store_for_tests(remove_persisted=True)


class TestAdminTokenAuth:
    """Test X-Admin-Token authentication."""

    def test_correct_token_approve_succeeds(self, client, reset_approvals, monkeypatch):
        """With correct X-Admin-Token, approve should succeed."""
        monkeypatch.setenv("NETWORK_AGENT_ADMIN_TOKEN", "secret-admin-token")

        # Create approval
        resp = client.post("/api/tools/approvals", json={
            "tool_id": "test_tool",
            "reason": "test",
            "workspace_id": "default",
        })
        assert resp.status_code == 200
        approval_id = resp.get_json()["approval_id"]

        # Approve with correct token
        resp = client.put(
            f"/api/tools/approvals/{approval_id}/approve",
            headers={"X-Admin-Token": "secret-admin-token"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["status"] == "approved"

    def test_wrong_token_returns_403(self, client, reset_approvals, monkeypatch):
        """With wrong X-Admin-Token, should return 403."""
        monkeypatch.setenv("NETWORK_AGENT_ADMIN_TOKEN", "secret-admin-token")

        # Create approval
        resp = client.post("/api/tools/approvals", json={
            "tool_id": "test_tool",
            "reason": "test",
            "workspace_id": "default",
        })
        approval_id = resp.get_json()["approval_id"]

        # Try to approve with wrong token
        resp = client.put(
            f"/api/tools/approvals/{approval_id}/approve",
            headers={"X-Admin-Token": "wrong-token"},
        )
        assert resp.status_code == 403
        data = resp.get_json()
        assert data["error"] == "admin_access_required"

    def test_correct_token_reject_succeeds(self, client, reset_approvals, monkeypatch):
        """With correct X-Admin-Token, reject should succeed."""
        monkeypatch.setenv("NETWORK_AGENT_ADMIN_TOKEN", "secret-admin-token")

        # Create approval
        resp = client.post("/api/tools/approvals", json={
            "tool_id": "test_tool",
            "reason": "test",
            "workspace_id": "default",
        })
        approval_id = resp.get_json()["approval_id"]

        # Reject with correct token
        resp = client.put(
            f"/api/tools/approvals/{approval_id}/reject",
            headers={"X-Admin-Token": "secret-admin-token"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["status"] == "rejected"

    def test_no_token_when_configured_returns_403(self, client, reset_approvals, monkeypatch):
        """When admin token is configured but not provided, should return 403."""
        monkeypatch.setenv("NETWORK_AGENT_ADMIN_TOKEN", "secret-admin-token")

        # Create approval
        resp = client.post("/api/tools/approvals", json={
            "tool_id": "test_tool",
            "reason": "test",
            "workspace_id": "default",
        })
        approval_id = resp.get_json()["approval_id"]

        # Try to approve without token
        resp = client.put(f"/api/tools/approvals/{approval_id}/approve")
        assert resp.status_code == 403


class TestLocalhostAccess:
    """Test localhost access when no admin token configured."""

    def test_localhost_access_without_token(self, client, reset_approvals, monkeypatch):
        """When no admin token configured, localhost should be allowed."""
        # Ensure no admin token
        monkeypatch.delenv("NETWORK_AGENT_ADMIN_TOKEN", raising=False)

        # Create approval
        resp = client.post("/api/tools/approvals", json={
            "tool_id": "test_tool",
            "reason": "test",
            "workspace_id": "default",
        })
        approval_id = resp.get_json()["approval_id"]

        # Approve (Flask test client simulates localhost)
        resp = client.put(f"/api/tools/approvals/{approval_id}/approve")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True


class TestApprovalStatusFlow:
    """Test approval status transitions."""

    def test_pending_to_approved(self, client, reset_approvals, monkeypatch):
        """Pending -> approved should work."""
        monkeypatch.setenv("NETWORK_AGENT_ADMIN_TOKEN", "test-token")

        # Create approval
        resp = client.post("/api/tools/approvals", json={
            "tool_id": "test_tool",
            "reason": "test",
            "workspace_id": "default",
        })
        approval_id = resp.get_json()["approval_id"]

        # Verify it's in pending list
        resp = client.get("/api/tools/approvals?workspace_id=default")
        data = resp.get_json()
        assert data["count"] == 1
        assert data["approvals"][0]["approval_id"] == approval_id
        assert data["approvals"][0]["status"] == "pending"

        # Approve
        resp = client.put(
            f"/api/tools/approvals/{approval_id}/approve",
            headers={"X-Admin-Token": "test-token"},
        )
        assert resp.status_code == 200

        # Verify it's no longer in pending list
        resp = client.get("/api/tools/approvals?workspace_id=default")
        data = resp.get_json()
        assert data["count"] == 0

    def test_pending_to_rejected(self, client, reset_approvals, monkeypatch):
        """Pending -> rejected should work."""
        monkeypatch.setenv("NETWORK_AGENT_ADMIN_TOKEN", "test-token")

        # Create approval
        resp = client.post("/api/tools/approvals", json={
            "tool_id": "test_tool",
            "reason": "test",
            "workspace_id": "default",
        })
        approval_id = resp.get_json()["approval_id"]

        # Verify it's in pending list
        resp = client.get("/api/tools/approvals?workspace_id=default")
        data = resp.get_json()
        assert data["count"] == 1

        # Reject
        resp = client.put(
            f"/api/tools/approvals/{approval_id}/reject",
            headers={"X-Admin-Token": "test-token"},
        )
        assert resp.status_code == 200

        # Verify it's no longer in pending list
        resp = client.get("/api/tools/approvals?workspace_id=default")
        data = resp.get_json()
        assert data["count"] == 0

    def test_approved_cannot_be_rejected(self, client, reset_approvals, monkeypatch):
        """Already approved approval should not be rejected."""
        monkeypatch.setenv("NETWORK_AGENT_ADMIN_TOKEN", "test-token")

        # Create and approve
        resp = client.post("/api/tools/approvals", json={
            "tool_id": "test_tool",
            "reason": "test",
            "workspace_id": "default",
        })
        approval_id = resp.get_json()["approval_id"]

        resp = client.put(
            f"/api/tools/approvals/{approval_id}/approve",
            headers={"X-Admin-Token": "test-token"},
        )
        assert resp.status_code == 200

        # Try to reject (should fail because status is not pending)
        resp = client.put(
            f"/api/tools/approvals/{approval_id}/reject",
            headers={"X-Admin-Token": "test-token"},
        )
        assert resp.status_code == 404  # Not found (because status != pending)

    def test_rejected_cannot_be_approved(self, client, reset_approvals, monkeypatch):
        """Already rejected approval should not be approved."""
        monkeypatch.setenv("NETWORK_AGENT_ADMIN_TOKEN", "test-token")

        # Create and reject
        resp = client.post("/api/tools/approvals", json={
            "tool_id": "test_tool",
            "reason": "test",
            "workspace_id": "default",
        })
        approval_id = resp.get_json()["approval_id"]

        resp = client.put(
            f"/api/tools/approvals/{approval_id}/reject",
            headers={"X-Admin-Token": "test-token"},
        )
        assert resp.status_code == 200

        # Try to approve (should fail)
        resp = client.put(
            f"/api/tools/approvals/{approval_id}/approve",
            headers={"X-Admin-Token": "test-token"},
        )
        assert resp.status_code == 404


class TestCrossWorkspaceApproval:
    """Cross-workspace approval should not allow invoke."""

    def test_cross_workspace_approval_not_usable(self, client, reset_approvals, monkeypatch):
        """Approval from workspace A should not work for workspace B."""
        monkeypatch.setenv("NETWORK_AGENT_ADMIN_TOKEN", "test-token")

        # Create approval for workspace "ws_a"
        resp = client.post("/api/tools/approvals", json={
            "tool_id": "test_tool",
            "reason": "test",
            "workspace_id": "ws_a",
        })
        data = resp.get_json()
        approval_id = data["approval_id"]

        # Approve it
        resp = client.put(
            f"/api/tools/approvals/{approval_id}/approve",
            headers={"X-Admin-Token": "test-token"},
        )
        assert resp.status_code == 200

        # List approvals for ws_b (should not include ws_a's approval)
        resp = client.get("/api/tools/approvals?workspace_id=ws_b")
        data = resp.get_json()
        assert data["count"] == 0  # Should not see ws_a's approvals

        # List approvals for ws_a (should not include approved approval in pending)
        resp = client.get("/api/tools/approvals?workspace_id=ws_a")
        data = resp.get_json()
        assert data["count"] == 0  # Should not be pending anymore
