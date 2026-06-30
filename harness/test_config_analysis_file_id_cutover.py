# harness/test_config_analysis_file_id_cutover.py
"""Config analysis file_id end-to-end tests."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def config_ws(monkeypatch, tmp_path):
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


def test_config_analysis_importable():
    """config.analysis module must be importable."""
    from agent.modules.config_analysis.service import run_config_analysis


def test_config_analysis_filepath_works(config_ws):
    """run_config_analysis should read workspace-relative filepath."""
    from agent.modules.config_analysis.service import run_config_analysis
    from storage.paths import workspace_root

    path = workspace_root("test_ws") / "configs" / "edge.cfg"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("interface GigabitEthernet0/0/1\n description uplink\n", encoding="utf-8")

    result = run_config_analysis(
        action="extract_interfaces",
        filepath="configs/edge.cfg",
        source_vendor="cisco_ios",
        workspace_id="test_ws",
    )
    assert result["ok"] is True
    assert result["interfaces"][0]["name"] == "GigabitEthernet0/0/1"


def test_config_analysis_file_id_only_no_source_config(config_ws):
    """run_config_analysis should work with file_id only, no source_config."""
    from storage.file_store import write_agent_output
    from agent.modules.config_analysis.service import run_config_analysis

    rec = write_agent_output(
        "test_ws",
        "interface GigabitEthernet0/0/1\n description uplink\n ip address 10.0.0.1 255.255.255.0\n",
        "config_input", "text", title="test config",
    )

    result = run_config_analysis(
        action="extract_interfaces",
        workspace_id="test_ws",
        file_id=rec.file_id,
    )
    assert isinstance(result, dict)
    assert "ok" in result or "error" not in str(result).lower()[:50]
