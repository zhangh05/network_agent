# harness/test_storage_legacy_migration.py
"""Tests for the legacy storage migration tool."""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def legacy_ws(monkeypatch, tmp_path):
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

    # Create legacy artifacts
    upload_dir = ws / "test_ws" / "files" / "upload"
    upload_dir.mkdir(parents=True, exist_ok=True)
    (upload_dir / "device.cfg").write_text("interface Eth0/0\n description test")

    agent_dir = ws / "test_ws" / "files" / "agent"
    agent_dir.mkdir(parents=True, exist_ok=True)

    # Legacy artifact content + meta
    art_id = "test_art_legacy"
    content_path = agent_dir / f"{art_id}.txt"
    content_path.write_text("legacy artifact content")
    meta_path = agent_dir / f"{art_id}.meta.json"
    meta_path.write_text(json.dumps({
        "artifact_id": art_id,
        "workspace_id": "test_ws",
        "artifact_type": "report",
        "title": "Legacy Report",
        "path": str(content_path),
        "relative_path": f"{art_id}.txt",
        "sensitivity": "internal",
        "lifecycle": "active",
    }))

    # PCAP sidecar in a different location
    pcap_meta = ws / "test_ws" / "runs" / "capture.meta.json"
    pcap_meta.parent.mkdir(parents=True, exist_ok=True)
    pcap_meta.write_text(json.dumps({
        "session_id": "sess_pcap_1",
        "filepath": str(ws / "test_ws" / "files" / "upload" / "capture.pcap"),
        "filename": "capture.pcap",
        "total_packets": 100,
        "connections": [{"src": "10.0.0.1", "dst": "10.0.0.2"}],
    }))

    return ws


def test_scan_detects_legacy_paths(legacy_ws):
    from storage.legacy_migration import scan_workspace_legacy_paths

    scan = scan_workspace_legacy_paths("test_ws")
    assert scan["workspace_id"] == "test_ws"
    assert len(scan["legacy_upload_files"]) >= 1
    assert len(scan["legacy_artifact_meta_files"]) >= 1
    assert len(scan["legacy_pcap_sidecar_files"]) >= 1


def test_dry_run_does_not_modify_index(legacy_ws):
    from storage.legacy_migration import migrate_workspace_legacy_paths
    from storage.file_store import list_files

    before = list_files("test_ws", lifecycle="")
    result = migrate_workspace_legacy_paths("test_ws", dry_run=True)
    after = list_files("test_ws", lifecycle="")

    assert result["dry_run"] is True
    assert len(before) == len(after), "dry-run must not modify index"


def test_apply_migrates_upload_files(legacy_ws):
    from storage.legacy_migration import migrate_workspace_legacy_paths
    from storage.file_store import list_files

    result = migrate_workspace_legacy_paths("test_ws", dry_run=False)
    assert "errors" in result

    files = list_files("test_ws", lifecycle="")
    assert len(files) >= 1, "Upload file should have FileRecord after migration"


def test_dry_run_migrated_is_empty(legacy_ws):
    from storage.legacy_migration import migrate_workspace_legacy_paths

    result = migrate_workspace_legacy_paths("test_ws", dry_run=True)
    assert result["dry_run"] is True
    assert result["planned"]
    assert result["migrated"] == [], f"dry-run migrated must be empty, got {result['migrated']}"
    assert result["errors"] == []


def test_apply_migrated_has_results(legacy_ws):
    from storage.legacy_migration import migrate_workspace_legacy_paths

    result = migrate_workspace_legacy_paths("test_ws", dry_run=False)
    assert result["dry_run"] is False
    assert result["migrated"], "apply must populate migrated"
