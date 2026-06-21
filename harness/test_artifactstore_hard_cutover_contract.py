# harness/test_artifactstore_hard_cutover_contract.py
"""Scan contract for ArtifactStore hard cutover runtime paths."""

from pathlib import Path


def test_artifact_runtime_uses_file_store_interfaces():
    project_root = Path(__file__).resolve().parents[1]
    store_text = (project_root / "artifacts" / "store.py").read_text(encoding="utf-8")
    file_tools_text = (
        project_root / "tool_runtime" / "general_tools" / "file_tools.py"
    ).read_text(encoding="utf-8")
    artifact_tools_text = (
        project_root / "tool_runtime" / "general_tools" / "artifact_tools.py"
    ).read_text(encoding="utf-8")

    assert "write_agent_output" in store_text
    assert "write_agent_output" in file_tools_text
    assert "read_artifact_content" in artifact_tools_text
