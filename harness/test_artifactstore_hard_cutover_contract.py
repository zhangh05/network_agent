# harness/test_artifactstore_hard_cutover_contract.py
"""Scan contract for ArtifactStore hard cutover runtime paths."""

from pathlib import Path


def test_artifact_runtime_no_direct_legacy_agent_meta_writes():
    project_root = Path(__file__).resolve().parents[1]
    paths = [
        project_root / "artifacts" / "store.py",
        project_root / "tool_runtime" / "general_tools" / "artifact_tools.py",
        project_root / "tool_runtime" / "general_tools" / "file_tools.py",
    ]
    forbidden = [
        "Fallback to legacy write",
        "files\" / \"agent",
        "files\" / \"upload",
        "fpath.write_text(content)",
        "_persist_artifact_tags",
        "for src in (\"agent\", \"upload\")",
        "for src in (\"upload\", \"agent\")",
    ]
    hits = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in text:
                hits.append((str(path.relative_to(project_root)), token))
    assert hits == []
