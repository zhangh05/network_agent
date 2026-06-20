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
    """run_config_analysis should still work with filepath parameter."""
    from agent.modules.config_analysis.service import run_config_analysis

    result = run_config_analysis(
        action="translate",
        source_config="interface GigabitEthernet0/0/1\n",
        source_vendor="cisco_ios",
        target_vendor="huawei_vrp",
        workspace_id="test_ws",
    )
    assert isinstance(result, dict)


def test_config_analysis_accepts_file_id(config_ws):
    """run_config_analysis should accept file_id parameter."""
    from storage.file_store import write_agent_output
    from agent.modules.config_analysis.service import run_config_analysis

    rec = write_agent_output("test_ws", "interface Eth0/0\n", "config_input", "text", title="test")

    result = run_config_analysis(
        action="translate",
        source_config="interface Eth0/0\n",
        source_vendor="cisco_ios",
        target_vendor="huawei_vrp",
        workspace_id="test_ws",
        source_file_id=rec.file_id,
    )
    assert isinstance(result, dict)
