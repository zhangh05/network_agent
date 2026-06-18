"""Session API Contract — validate HTTP endpoint behavior and response shapes.

Tests the full lifecycle via Flask test_client:
  create → list → get → run association → archive → restore → soft-delete → permanent delete
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.main import create_app


class TestSessionAPIContract:
    def setup_method(self):
        self.app = create_app()
        self.client = self.app.test_client()
        self.ws = "api_contract_test"

    def test_create_session(self):
        resp = self.client.post("/api/sessions", json={
            "workspace_id": self.ws,
            "title": "Contract Test",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["session"]["session_id"]
        assert data["session"]["title"] == "Contract Test"
        assert data["session"]["status"] == "active"

    def test_list_sessions_pagination(self):
        # Create a few sessions
        for i in range(3):
            self.client.post("/api/sessions", json={
                "workspace_id": self.ws,
                "title": f"List Test {i}",
            })
        resp = self.client.get(f"/api/sessions?workspace_id={self.ws}&limit=2")
        data = resp.get_json()
        assert data["ok"] is True
        assert len(data["sessions"]) <= 2
        assert "counts" in data

    def test_list_sessions_status_filter(self):
        r = self.client.post("/api/sessions", json={
            "workspace_id": self.ws,
            "title": "Filtered",
        })
        sid = r.get_json()["session"]["session_id"]
        self.client.post(f"/api/sessions/{sid}/archive?workspace_id={self.ws}")

        active = self.client.get(f"/api/sessions?workspace_id={self.ws}&status=active").get_json()
        archived = self.client.get(f"/api/sessions?workspace_id={self.ws}&status=archived").get_json()
        active_ids = [s["session_id"] for s in active["sessions"]]
        archived_ids = [s["session_id"] for s in archived["sessions"]]
        assert sid not in active_ids
        assert sid in archived_ids

    def test_get_session_detail_with_messages(self):
        r = self.client.post("/api/sessions", json={
            "workspace_id": self.ws,
            "title": "Detail Test",
        })
        sid = r.get_json()["session"]["session_id"]
        resp = self.client.get(f"/api/sessions/{sid}?workspace_id={self.ws}&include_messages=1")
        data = resp.get_json()
        assert data["ok"] is True
        assert "session" in data
        assert "messages" in data
        assert len(data["messages"]) == 0

    def test_get_session_not_found(self):
        resp = self.client.get(f"/api/sessions/nonexistent?workspace_id={self.ws}")
        assert resp.status_code == 404
        data = resp.get_json()
        assert data["ok"] is False
        assert data["error"] == "session_not_found"

    def test_update_session(self):
        r = self.client.post("/api/sessions", json={
            "workspace_id": self.ws,
            "title": "Before Update",
        })
        sid = r.get_json()["session"]["session_id"]
        resp = self.client.put(f"/api/sessions/{sid}?workspace_id={self.ws}", json={
            "title": "After Update",
        })
        data = resp.get_json()
        assert data["ok"] is True
        assert data["session"]["title"] == "After Update"

    def test_agent_run_with_session_association(self):
        r = self.client.post("/api/sessions", json={
            "workspace_id": self.ws,
            "title": "Run Assoc API",
        })
        sid = r.get_json()["session"]["session_id"]
        resp = self.client.post("/api/agent/message", json={
            "message": "translate this config",
            "workspace_id": self.ws,
            "session_id": sid,
        })
        data = resp.get_json()
        # In CI without API key, skip strict ok check
        if not data.get("ok") and data.get("error_type") in ("missing_api_key", "provider_error", "disabled_by_user"):
            assert data.get("session_id") == sid
            return
        assert data["ok"] is True
        assert data.get("session_id") == sid

        # Verify session now has the run
        detail = self.client.get(f"/api/sessions/{sid}?workspace_id={self.ws}&include_messages=1").get_json()
        assert len(detail["messages"]) >= 2  # user + assistant

    def test_archive_restore_cycle(self):
        r = self.client.post("/api/sessions", json={
            "workspace_id": self.ws,
            "title": "Archive Cycle",
        })
        sid = r.get_json()["session"]["session_id"]

        # Archive
        resp = self.client.post(f"/api/sessions/{sid}/archive?workspace_id={self.ws}")
        assert resp.get_json()["session"]["status"] == "archived"

        # Restore
        resp = self.client.post(f"/api/sessions/{sid}/restore?workspace_id={self.ws}")
        assert resp.get_json()["session"]["status"] == "active"

    def test_soft_delete_preserves_runs(self):
        r = self.client.post("/api/sessions", json={
            "workspace_id": self.ws,
            "title": "Soft Delete",
        })
        sid = r.get_json()["session"]["session_id"]
        # Run something in the session
        self.client.post("/api/agent/message", json={
            "message": "hello",
            "workspace_id": self.ws,
            "session_id": sid,
        })
        # Soft delete
        resp = self.client.post(f"/api/sessions/{sid}/soft-delete?workspace_id={self.ws}")
        assert resp.get_json()["session"]["status"] == "deleted"
        # Run record should still exist
        from workspace.run_store import list_runs
        runs = list_runs(self.ws, limit=10)
        assert len(runs) > 0

    def test_permanent_delete_needs_confirm(self):
        r = self.client.post("/api/sessions", json={
            "workspace_id": self.ws,
            "title": "Perm Delete",
        })
        sid = r.get_json()["session"]["session_id"]
        # Without confirm
        resp = self.client.delete(f"/api/sessions/{sid}?workspace_id={self.ws}")
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["error"] == "confirm_required"
        # With confirm
        resp = self.client.delete(f"/api/sessions/{sid}?workspace_id={self.ws}&confirm=true")
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True
        # Verify gone
        resp = self.client.get(f"/api/sessions/{sid}?workspace_id={self.ws}")
        assert resp.status_code == 404

    def test_default_session_endpoint(self):
        resp = self.client.get(f"/api/sessions/default?workspace_id={self.ws}")
        data = resp.get_json()
        assert data["ok"] is True
        assert data["session"]["status"] == "active"
        assert data["session"]["session_id"]

    def test_invalid_workspace_rejected(self):
        resp = self.client.post("/api/sessions", json={"workspace_id": "../../etc"})
        assert resp.status_code == 400


if __name__ == "__main__":
    t = TestSessionAPIContract()
    total = 0
    passed = 0
    failed = 0
    for name in dir(t):
        if name.startswith("test_"):
            total += 1
            try:
                t.setup_method()
                getattr(t, name)()
                passed += 1
                print(f"  PASS: {name}")
            except Exception as e:
                failed += 1
                print(f"  FAIL: {name} — {e}")
    print(f"\n{total} tests, {passed} passed, {failed} failed")
