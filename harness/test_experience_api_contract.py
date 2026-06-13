"""User experience API contracts for the React workbench."""

import json
import pytest

from backend.main import app as _flask_app


@pytest.fixture
def client(temp_dirs):
    _flask_app.config["TESTING"] = True
    return _flask_app.test_client()


def test_workspaces_default_first_and_frontend_shape(client):
    resp = client.get("/api/workspaces")
    assert resp.status_code == 200
    workspaces = resp.get_json()["workspaces"]
    assert workspaces
    assert workspaces[0]["workspace_id"] == "default"
    assert workspaces[0]["is_default"] is True
    assert workspaces[0]["name"] == "default"
    assert "stats" in workspaces[0]
    assert "session_count" in workspaces[0]["stats"]
    assert "artifact_count" in workspaces[0]["stats"]
    assert "knowledge_source_count" in workspaces[0]["stats"]


def test_workspace_session_count_tracks_active_sessions(client):
    from workspace.manager import WS_ROOT, ensure_workspace

    ensure_workspace("default")
    sessions_dir = WS_ROOT / "default" / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    for session_id, status in (
        ("active", "active"),
        ("archived", "archived"),
        ("deleted", "deleted"),
    ):
        (sessions_dir / f"{session_id}.json").write_text(
            json.dumps({
                "session_id": session_id,
                "workspace_id": "default",
                "title": session_id,
                "status": status,
            }),
            encoding="utf-8",
        )

    resp = client.get("/api/workspaces")
    assert resp.status_code == 200
    default_ws = resp.get_json()["workspaces"][0]
    assert default_ws["workspace_id"] == "default"
    assert default_ws["stats"]["session_count"] == 1


def test_runtime_summary_reports_capabilities_and_tool_visibility(client):
    resp = client.get("/api/runtime/summary")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["capabilities"] == {
        "total": 7,
        "enabled": 4,
        "planned": 3,
        "disabled": 0,
    }
    assert data["tools"]["registered"] == 58
    assert data["tools"]["model_visible"] == 57
    assert "knowledge.read_source" in data["tools"]["hidden_or_non_llm"]
