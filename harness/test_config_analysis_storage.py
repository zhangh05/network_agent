# Configuration analysis storage contracts.
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


def test_config_translation_auto_detects_source_vendor(config_ws):
    from agent.modules.config_analysis.service import run_config_analysis

    result = run_config_analysis(
        action="translate",
        workspace_id="test_ws",
        source_config=(
            "hostname Edge01\n"
            "interface GigabitEthernet0/0\n"
            " ip address 10.0.0.1 255.255.255.0\n"
        ),
        source_vendor="auto",
        target_vendor="huawei",
        run_id="run_translate_auto",
        session_id="session_translate_auto",
    )

    assert result["ok"] is True
    assert result["source_vendor"] == "cisco"
    assert result["target_vendor"] == "huawei"
    assert len(result["artifacts"]) == 1


def test_config_translation_requires_explicit_target_vendor(config_ws):
    from agent.modules.config_analysis.service import run_config_analysis

    result = run_config_analysis(
        action="translate",
        workspace_id="test_ws",
        source_config="hostname Edge01\n",
        source_vendor="cisco",
    )

    assert result["ok"] is False
    assert result["errors"] == ["missing_target_vendor"]
    assert result["artifacts"] == []


def test_config_translation_does_not_guess_ambiguous_comware_vendor():
    from modules.config_translation.backend.service import detect_vendor

    assert detect_vendor("sysname Edge01\ndisplay current-configuration\n") == "unknown"


def test_config_translation_is_an_artifact_write_action():
    from core.runtime_engine.contracts import is_read_only_call

    assert is_read_only_call("config.manage", {"action": "parse"}) is True
    assert is_read_only_call("config.manage", {"action": "translate"}) is False


def test_config_translation_retry_reuses_run_artifact(config_ws):
    from agent.modules.config_analysis.service import run_config_analysis
    from artifacts.store import get_artifact, list_artifacts
    from storage.file_store import write_agent_output

    source = write_agent_output(
        "test_ws",
        "hostname Edge01\ninterface GigabitEthernet0/0\n description uplink\n",
        "config_input",
        "text",
        title="edge config",
    )
    kwargs = {
        "action": "translate",
        "workspace_id": "test_ws",
        "file_id": source.file_id,
        "source_vendor": "auto",
        "target_vendor": "h3c",
        "run_id": "run_translate_retry",
        "session_id": "session_translate_retry",
    }

    first = run_config_analysis(**kwargs)
    second = run_config_analysis(**kwargs)
    artifacts = list_artifacts(
        "test_ws",
        run_id="run_translate_retry",
        artifact_type="translated_config",
    )

    assert first["ok"] is True and second["ok"] is True
    assert first["artifacts"][0]["artifact_id"] == second["artifacts"][0]["artifact_id"]
    assert len(artifacts) == 1
    stored = get_artifact("test_ws", artifacts[0]["artifact_id"])
    assert stored is not None
    assert stored.session_id == "session_translate_retry"
    assert artifacts[0]["metadata"]["source_file_id"] == source.file_id
