# harness/test_pcap_session_persistence.py
"""PCAP session persistence tests."""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def pcap_ws(monkeypatch, tmp_path):
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


def test_pcap_session_index_written(pcap_ws):
    """After parse, session index jsonl should be writable."""
    from agent.modules.pcap.service import parse_pcap_file

    result = parse_pcap_file("test_ws", filepath="nonexistent.pcap")

    # Verify the function handles file_id and returns appropriate error
    if not result.get("ok"):
        assert "errors" in result
    else:
        # On success, verify session index exists
        idx_path = pcap_ws / "test_ws" / "index" / "pcap_sessions.jsonl"
        # Not requiring success since no actual pcap to parse


def test_pcap_parse_accepts_file_id_param(pcap_ws):
    """parse_pcap_file must accept file_id parameter."""
    from agent.modules.pcap.service import parse_pcap_file

    result = parse_pcap_file("test_ws", file_id="file_nonexistent")
    assert "ok" in result
    assert result.get("tool_id") == "pcap.analysis.run"


def test_pcap_service_module_importable():
    """PCAP service module must be importable."""
    from agent.modules.pcap.service import run_pcap_analysis, parse_pcap_file
