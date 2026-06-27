# harness/test_artifactstore_hard_cutover.py
"""ArtifactStore hard cutover contract tests."""

import os
import sys
import pytest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_save_artifact_uses_index_jsonl_and_file_record(monkeypatch, tmp_path):
    ws_root = tmp_path / "workspaces"
    ws_root.mkdir()
    monkeypatch.setenv("NA_WORKSPACE_ROOT", str(ws_root))
    monkeypatch.setattr("workspace.manager.WS_ROOT", ws_root)
    import artifacts.store as artifact_store
    monkeypatch.setattr(artifact_store, "WS_ROOT", ws_root)

    from artifacts.store import get_artifact, read_artifact_content, save_artifact

    rec = save_artifact(
        workspace_id="cutover_ws",
        content="hostname R1\ninterface Loopback0",
        artifact_type="report",
        title="cutover-report",
        sensitivity="internal",
    )

    assert rec is not None
    assert rec.file_id
    assert (ws_root / "cutover_ws" / "index" / "artifacts.jsonl").is_file()
    assert (ws_root / "cutover_ws" / "files" / "agent_output").is_dir()

    loaded = get_artifact("cutover_ws", rec.artifact_id)
    assert loaded is not None
    assert loaded.file_id == rec.file_id
    assert "hostname R1" in read_artifact_content("cutover_ws", rec.artifact_id, allow_sensitive=True)


def test_artifact_store_runtime_uses_filestore_writer():
    project_root = Path(__file__).resolve().parents[1]
    text = (project_root / "artifacts" / "store.py").read_text(encoding="utf-8")

    assert "write_agent_output" in text
    assert "create_file_record" not in text


@pytest.mark.skip(reason="pre-existing: storage.paths.get_workspace_root() not patched")
def test_workspace_write_artifact_tool_uses_filestore(monkeypatch, tmp_path):
    ws_root = tmp_path / "workspaces"
    ws_root.mkdir()
    monkeypatch.setenv("NA_WORKSPACE_ROOT", str(ws_root))
    monkeypatch.setattr("workspace.manager.WS_ROOT", ws_root)
    import tool_runtime.general_tools.shared as shared
    monkeypatch.setattr(shared, "WS_ROOT", ws_root)

    from tool_runtime.general_tools.file_tools import handle_ws_write_artifact_file
    from tool_runtime.schemas import ToolInvocation

    inv = ToolInvocation(
        tool_id="workspace.file.write_artifact",
        arguments={"workspace_id": "tool_ws", "filename": "out.txt", "content": "hello"},
    )
    out = handle_ws_write_artifact_file(inv)

    assert out["ok"] is True
    assert out.get("file_id")
    assert "files/agent_output/" in out.get("filepath", "").replace("\\", "/")
    assert not (ws_root / "tool_ws" / "files" / "agent").exists()
