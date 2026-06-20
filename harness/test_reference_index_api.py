# harness/test_reference_index_api.py
"""Tests for the ReferenceIndex read API routes."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def api_ws(monkeypatch, tmp_path):
    ws = tmp_path / "workspaces"
    ws.mkdir()
    monkeypatch.setenv("NA_WORKSPACE_ROOT", str(ws))
    monkeypatch.setenv("NETWORK_AGENT_WORKSPACE_DIR", str(ws))
    monkeypatch.setattr("workspace.manager.WS_ROOT", ws)
    try:
        import artifacts.store as _as
        monkeypatch.setattr(_as, "WS_ROOT", ws)
    except Exception:
        pass
    from storage.paths import ensure_workspace_storage_dirs
    ensure_workspace_storage_dirs("test_ws")
    return ws


def test_file_references_api_returns_empty_when_no_refs(api_ws, monkeypatch):
    monkeypatch.setattr("workspace.manager.WS_ROOT", api_ws)
    monkeypatch.setenv("NA_WORKSPACE_ROOT", str(api_ws))

    from backend.main import app
    client = app.test_client()

    resp = client.get("/api/workspaces/test_ws/files/file_nonexistent/references")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["references"] == []
    assert body["count"] == 0


def test_reference_graph_api(api_ws, monkeypatch):
    monkeypatch.setattr("workspace.manager.WS_ROOT", api_ws)
    monkeypatch.setenv("NA_WORKSPACE_ROOT", str(api_ws))

    from backend.main import app
    client = app.test_client()

    resp = client.get("/api/workspaces/test_ws/reference-graph")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert isinstance(body["nodes"], list)
    assert isinstance(body["edges"], list)
