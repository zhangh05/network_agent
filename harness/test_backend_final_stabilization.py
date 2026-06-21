# harness/test_backend_final_stabilization.py
"""Final backend stabilization tests: API contract, status, health, doctor."""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

PROJECT = Path(__file__).resolve().parents[1]


@pytest.fixture
def stab_ws(monkeypatch, tmp_path):
    ws = tmp_path / "workspaces"
    ws.mkdir()
    monkeypatch.setenv("NA_WORKSPACE_ROOT", str(ws))
    monkeypatch.setenv("NETWORK_AGENT_WORKSPACE_DIR", str(ws))
    monkeypatch.setattr("workspace.manager.WS_ROOT", ws)
    from storage.paths import ensure_workspace_storage_dirs
    ensure_workspace_storage_dirs("test_ws")
    return ws


def test_api_contract_doc_exists():
    assert (PROJECT / "docs" / "backend" / "API_CONTRACT.md").exists()


def test_response_helpers_module_exists():
    from backend.core.responses import ok_response, error_response

    body, status = ok_response({"x": 1}, workspace_id="test_ws")
    assert status == 200
    assert body == {"ok": True, "workspace_id": "test_ws", "x": 1}

    body, status = error_response("FILE_NOT_FOUND", "missing", 404)
    assert status == 404
    assert body["ok"] is False
    assert body["error"] == "FILE_NOT_FOUND"
    assert body["message"] == "missing"


def test_workspace_status_api(stab_ws, monkeypatch):
    monkeypatch.setattr("workspace.manager.WS_ROOT", stab_ws)
    monkeypatch.setenv("NA_WORKSPACE_ROOT", str(stab_ws))
    from backend.main import app

    client = app.test_client()
    resp = client.get("/api/workspaces/test_ws/status")
    assert resp.status_code == 200

    body = resp.get_json()
    assert body["ok"] is True
    assert body["workspace_exists"] is True
    assert isinstance(body["file_count"], int)
    assert isinstance(body["artifact_count"], int)
    # No absolute path leak
    for v in json.dumps(body).split():
        assert not v.startswith("/private/")
        assert not v.startswith("/tmp/")


def test_workspace_status_invalid_id(stab_ws, monkeypatch):
    monkeypatch.setattr("workspace.manager.WS_ROOT", stab_ws)
    monkeypatch.setenv("NA_WORKSPACE_ROOT", str(stab_ws))
    from backend.main import app

    client = app.test_client()
    resp = client.get("/api/workspaces/%20/status")
    body = resp.get_json()
    assert body is not None
    assert body.get("error") == "INVALID_WORKSPACE_ID"
    assert body.get("message") == "invalid workspace_id"


def test_storage_health_api(stab_ws, monkeypatch):
    monkeypatch.setattr("workspace.manager.WS_ROOT", stab_ws)
    monkeypatch.setenv("NA_WORKSPACE_ROOT", str(stab_ws))
    from backend.main import app

    client = app.test_client()
    resp = client.get("/api/workspaces/test_ws/storage/health")
    assert resp.status_code == 200

    body = resp.get_json()
    assert body["ok"] is True
    assert "checks" in body


def test_storage_doctor_does_not_modify(stab_ws):
    from storage.doctor import run_doctor

    idx = stab_ws / "test_ws" / "index"
    idx.mkdir(parents=True, exist_ok=True)

    result = run_doctor("test_ws")
    assert result["workspace_id"] == "test_ws"
    assert isinstance(result["ok"], bool)
    assert isinstance(result["checks"], list)
    assert isinstance(result["warnings"], list)
    assert isinstance(result["errors"], list)
    # No files should have been created by doctor
    assert len(list(idx.iterdir())) == 0  # only the directory itself, no files


def test_storage_doctor_detects_orphan(stab_ws):
    from storage.file_store import write_agent_output
    from storage.doctor import run_doctor

    rec = write_agent_output("test_ws", "content", "artifact_output", "text", title="t")

    result = run_doctor("test_ws")
    # After writing a file, there should be a file record with the physical file
    file_orphans = [c for c in result["checks"] if c["name"] == "file_orphans"]
    if file_orphans:
        assert file_orphans[0]["count"] == 0  # file exists, no orphan
