"""Storage cutover contract tests."""

from pathlib import Path


def test_new_workspace_creates_current_storage_dirs(monkeypatch, tmp_path):
    ws = tmp_path / "workspaces"
    ws.mkdir()
    monkeypatch.setenv("NA_WORKSPACE_ROOT", str(ws))
    monkeypatch.setattr("workspace.manager.WS_ROOT", ws)

    from workspace.manager import ensure_workspace

    ensure_workspace("test_ws")

    assert (ws / "test_ws" / "files" / "user_upload" / "original").is_dir()
    assert (ws / "test_ws" / "files" / "agent_output" / "export").is_dir()


def test_knowledge_allowed_roots_use_current_storage():
    from agent.modules.knowledge.ingestion import _allowed_import_roots

    roots = _allowed_import_roots("test_ws")
    root_paths = [str(r).replace("\\", "/") for r in roots]
    assert any(path.endswith("/files/user_upload") for path in root_paths)
    assert any(path.endswith("/files/agent_output") for path in root_paths)


def test_artifact_content_has_no_path_fallback():
    project_root = Path(__file__).resolve().parents[1]
    text = (project_root / "artifacts" / "store.py").read_text(encoding="utf-8")
    assert "read_file_content(workspace_id, file_id)" in text


def test_pcap_service_has_no_sidecar_fallback():
    project_root = Path(__file__).resolve().parents[1]
    service = (project_root / "agent" / "modules" / "pcap" / "service.py").read_text(encoding="utf-8")
    core = (project_root / "agent" / "modules" / "pcap" / "core.py").read_text(encoding="utf-8")
    assert "load_session_from_file" not in service
    assert "session_meta_path" not in service
    assert "load_session_from_file" not in core
    assert "session_meta_path" not in core
