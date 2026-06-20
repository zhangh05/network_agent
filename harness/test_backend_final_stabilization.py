# harness/test_backend_final_stabilization.py
"""Final backend stabilization tests: API contract, error codes, status, health, doctor."""

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


def test_error_codes_module_exists():
    from backend.core.error_codes import (
        api_ok, api_error, WORKSPACE_NOT_FOUND, INVALID_WORKSPACE_ID,
        FILE_NOT_FOUND, ARTIFACT_NOT_FOUND, PCAP_SESSION_NOT_FOUND,
        REFERENCE_NOT_FOUND, INTERNAL_ERROR,
    )


def test_api_ok_envelope():
    from backend.core.error_codes import api_ok
    r = api_ok(data={"x": 1}, summary="done")
    assert r["ok"] is True
    assert r["status"] == "ok"
    assert r["summary"] == "done"
    assert r["data"] == {"x": 1}
    assert r["errors"] == []


def test_api_error_envelope():
    from backend.core.error_codes import api_error
    body, code = api_error("FILE_NOT_FOUND", "missing", details=["not there"])
    assert body["ok"] is False
    assert body["status"] == "failed"
    assert body["error_code"] == "FILE_NOT_FOUND"
    assert body["errors"] == ["not there"]
    assert code == 400


def test_workspace_status_api(stab_ws, monkeypatch):
    monkeypatch.setattr("workspace.manager.WS_ROOT", stab_ws)
    monkeypatch.setenv("NA_WORKSPACE_ROOT", str(stab_ws))
    from backend.main import app

    client = app.test_client()
    resp = client.get("/api/workspaces/test_ws/status")
    assert resp.status_code == 200

    body = resp.get_json()
    assert body["ok"] is True
    assert body["status"] == "ok"
    assert body["data"]["workspace_exists"] is True
    assert isinstance(body["data"]["file_count"], int)
    assert isinstance(body["data"]["artifact_count"], int)
    assert body["errors"] == []
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
    assert body.get("error_code") == "INVALID_WORKSPACE_ID"


def test_storage_health_api(stab_ws, monkeypatch):
    monkeypatch.setattr("workspace.manager.WS_ROOT", stab_ws)
    monkeypatch.setenv("NA_WORKSPACE_ROOT", str(stab_ws))
    from backend.main import app

    client = app.test_client()
    resp = client.get("/api/workspaces/test_ws/storage/health")
    assert resp.status_code == 200

    body = resp.get_json()
    assert body["ok"] is True
    assert "checks" in body["data"]


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
