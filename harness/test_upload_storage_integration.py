# Upload storage integration contracts.
"""Tests for the upload pipeline migration to FileStore."""

import io
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    from backend.main import app as _flask_app
except ImportError:
    _flask_app = None


@pytest.fixture
def upload_client(monkeypatch, tmp_path):
    """Flask test client with all workspace paths redirected to tmp."""
    if _flask_app is None:
        pytest.skip("Flask app not importable")

    ws_dir = tmp_path / "workspaces"
    ws_dir.mkdir()

    monkeypatch.setenv("NA_WORKSPACE_ROOT", str(ws_dir))
    monkeypatch.setattr("workspace.manager.WS_ROOT", ws_dir)

    try:
        import artifacts.store as _as
        monkeypatch.setattr(_as, "WS_ROOT", ws_dir)
    except Exception:
        pass

    _flask_app.config["TESTING"] = True
    return _flask_app.test_client()


def test_text_upload_preserves_file_and_creates_artifact(upload_client, tmp_path):
    data = {
        "file": (io.BytesIO(b"interface GigabitEthernet0/0/1\n description test\n"), "device.cfg"),
        "artifact_type": "config_input",
        "title": "device config",
        "scope": "workspace",
    }

    resp = upload_client.post(
        "/api/workspaces/default/artifacts/upload",
        data=data,
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["file"]["file_id"].startswith("file_")
    assert body["file"]["logical_type"] == "config_input"
    assert body["artifact"] is not None
    assert body["artifact"]["artifact_id"]


def test_pcap_upload_preserves_binary_without_text_artifact(upload_client, tmp_path):
    data = {
        "file": (io.BytesIO(b"\xd4\xc3\xb2\xa1\x00\x00\x00\x00"), "sample.pcap"),
        "artifact_type": "pcap_input",
        "title": "sample pcap",
    }

    resp = upload_client.post(
        "/api/workspaces/default/artifacts/upload",
        data=data,
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["file"]["file_id"].startswith("file_")
    assert body["file"]["logical_type"] == "pcap_input"
    assert body["file"]["binary"] is True
    assert body["artifact"] is None
    assert "binary_upload_preserved_as_file_only" in body["warnings"]


def test_upload_no_file_returns_400(upload_client):
    resp = upload_client.post(
        "/api/workspaces/default/artifacts/upload",
        data={},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "no file provided"


def test_guess_upload_kind():
    from backend.api.artifact_routes import _guess_upload_kind

    assert _guess_upload_kind("test.pcap") == ("pcap", True)
    assert _guess_upload_kind("test.pcapng") == ("pcap", True)
    assert _guess_upload_kind("test.pdf") == ("pdf", True)
    assert _guess_upload_kind("test.docx") == ("docx", True)
    assert _guess_upload_kind("test.cfg") == ("config", False)
    assert _guess_upload_kind("test.txt") == ("config", False)
    assert _guess_upload_kind("test.json") == ("json", False)
    assert _guess_upload_kind("test.md") == ("markdown", False)
    assert _guess_upload_kind("unknown.xyz")[1] is False  # text, not binary
