"""Files API JSON-create contracts."""

import pytest

from backend.main import app as _flask_app


@pytest.fixture
def client(temp_dirs):
    _flask_app.config["TESTING"] = True
    return _flask_app.test_client()


def test_json_create_preserves_metadata_and_hidden(client):
    resp = client.post(
        "/api/files",
        json={
            "workspace_id": "ws-json",
            "title": "pcap-analysis",
            "type": "pcap_analysis",
            "source": "agent",
            "hidden": True,
            "metadata": {"session_id": "sid-1", "flow": "a:b"},
            "content": "{}",
            "extension": "json",
        },
    )

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["workspace_id"] == "ws-json"
    assert data["type"] == "pcap_analysis"
    assert data["hidden"] is True
    assert data["metadata"] == {"session_id": "sid-1", "flow": "a:b"}

    listed = client.get("/api/files?workspace_id=ws-json").get_json()
    assert listed["count"] == 0
