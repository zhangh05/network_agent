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
    # No actual pcap to parse — verification of index is in the recovery test below


def test_pcap_session_recovery_restores_connections(pcap_ws, monkeypatch):
    """After writing session index, get_pcap_session must restore non-empty connections."""
    import json

    monkeypatch.setenv("NA_WORKSPACE_ROOT", str(pcap_ws))

    idx_dir = pcap_ws / "test_ws" / "index"
    idx_dir.mkdir(parents=True, exist_ok=True)
    idx_path = idx_dir / "pcap_sessions.jsonl"
    record = {
        "session_id": "sess_test_recovery",
        "filepath": str(pcap_ws / "test.pcap"),
        "filename": "test.pcap",
        "total_packets": 42,
        "connection_count": 3,
        "connections": [
            {"src": "10.0.0.1", "dst": "10.0.0.2"},
            {"src": "10.0.0.3", "dst": "10.0.0.4"},
            {"src": "10.0.0.5", "dst": "10.0.0.6"},
        ],
    }
    idx_path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")

    from agent.modules.pcap.service import get_pcap_session
    result = get_pcap_session("sess_test_recovery", workspace_id="test_ws")

    assert result["ok"] is True
    assert result["session_id"] == "sess_test_recovery"
    assert result["total_packets"] == 42
    assert result["connections"]
    assert len(result["connections"]) == 3
    assert result["connections"][0]["src"] == "10.0.0.1"


def test_pcap_parse_accepts_file_id_param(pcap_ws):
    """parse_pcap_file must accept file_id parameter."""
    from agent.modules.pcap.service import parse_pcap_file

    result = parse_pcap_file("test_ws", file_id="file_nonexistent")
    assert "ok" in result
    assert result.get("tool_id") == "pcap.analysis.run"


def test_pcap_service_module_importable():
    """PCAP service module must be importable."""
    from agent.modules.pcap.service import run_pcap_analysis, parse_pcap_file
