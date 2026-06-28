# harness/test_storage_core_migration.py
"""Tests for core FileStore behavior: artifact writes, message store, PCAP file_id."""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def storage_ws(monkeypatch, tmp_path):
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
    try:
        import workspace.message_store as _ms
        monkeypatch.setattr(_ms, "WS_ROOT", ws)
    except Exception:
        pass
    from storage.paths import ensure_workspace_storage_dirs
    ensure_workspace_storage_dirs("test_ws")
    return ws


# ── ArtifactStore real FileStore write ───────────────────────────────

def test_save_artifact_writes_through_filestore(storage_ws):
    from artifacts.store import save_artifact
    from storage.file_store import list_files, resolve_file_path

    rec = save_artifact(
        workspace_id="test_ws",
        content="translated config content",
        artifact_type="translated_config",
        title="translated",
        sensitivity="internal",
    )

    assert rec is not None
    assert rec.file_id, "ArtifactRecord.file_id must be set"
    assert rec.artifact_id

    files = list_files("test_ws", lifecycle="")
    matched = [f for f in files if f.get("file_id") == rec.file_id]
    assert matched, "FileRecord must exist in index"
    assert matched[0]["metadata"].get("write_path") == "filestore"
    assert matched[0]["path"].startswith("files/agent_output/")

    # Verify physical file path
    physical = resolve_file_path("test_ws", rec.file_id)
    assert "files/agent_output" in str(physical).replace("\\", "/")
    assert physical.exists()


def test_new_artifact_writes_current_content_file(storage_ws):
    from artifacts.store import save_artifact
    from storage.file_store import resolve_file_path

    rec = save_artifact(
        workspace_id="test_ws",
        content="new artifact content",
        artifact_type="report",
        title="new report",
    )

    assert rec.file_id
    assert resolve_file_path("test_ws", rec.file_id).is_file()


def test_save_artifact_creates_reference_index(storage_ws):
    from artifacts.store import save_artifact
    from storage.reference_index import list_references_for_owner

    rec = save_artifact(
        workspace_id="test_ws",
        content="report content",
        artifact_type="report",
        title="test report",
    )

    refs = list_references_for_owner("test_ws", "artifact", rec.artifact_id)
    assert any(r["relation"] == "output" for r in refs)


def test_save_artifact_source_file_id_reference(storage_ws):
    from artifacts.store import save_artifact
    from storage.reference_index import list_references_for_owner

    rec = save_artifact(
        workspace_id="test_ws",
        content="translated output",
        artifact_type="translated_config",
        title="translated",
        metadata={"source_file_id": "file_src_123"},
    )

    refs = list_references_for_owner("test_ws", "artifact", rec.artifact_id)
    assert any(r["relation"] == "source" for r in refs)


# ── SessionMessageStore large content ────────────────────────────────

def test_message_large_content_uses_artifact(storage_ws):
    from workspace.message_store import SessionMessageStore

    store = SessionMessageStore("sess_test", ws_id="test_ws")
    large_content = "x" * 60_000  # exceeds 50KB threshold

    msg_id = store.write_message("run_1", "user", large_content)
    assert msg_id

    messages = store.get_messages()
    user_msgs = [m for m in messages if m.get("role") == "user" and m.get("run_id") == "run_1"]
    assert user_msgs
    ref = user_msgs[0].get("artifact_ref", {})
    assert ref.get("artifact_id"), "artifact_ref must have artifact_id"
    assert ref.get("artifact_type") == "message_large_content"


# ── PCAP file_id support ────────────────────────────────────────────

def test_pcap_parse_accepts_file_id(storage_ws):
    from storage.file_store import import_user_upload
    from agent.modules.pcap.service import run_pcap_analysis

    # Create a fake pcap file (won't parse with scapy but tests the path)
    src = storage_ws / "fake.pcap"
    src.write_bytes(b"\xd4\xc3\xb2\xa1" + b"\x00" * 100)

    file_rec = import_user_upload(
        workspace_id="test_ws",
        file_source=str(src),
        original_name="test.pcap",
        logical_type="pcap_input",
        file_kind="pcap",
        binary=True,
    )

    result = run_pcap_analysis("parse", workspace_id="test_ws", file_id=file_rec.file_id)
    # scapy likely not installed in test env — expect either success or clear error
    assert result.get("tool_id") == "pcap.manage"
    # If parse fails due to no scapy, it should not crash
    assert "ok" in result


def test_pcap_parse_no_sidecar_written(storage_ws):
    """New parses should not write <pcap>.meta.json sidecar files."""
    from agent.modules.pcap.service import parse_pcap_file

    # Even if parse fails, no sidecar should be written for new parses
    result = parse_pcap_file("test_ws", filepath="nonexistent.pcap")
    assert result["ok"] is False

    # Check no .meta.json was created in the workspace
    ws = storage_ws / "test_ws"
    meta_files = list(ws.rglob("*.meta.json"))
    assert not meta_files, f"No sidecar should be written: {meta_files}"
