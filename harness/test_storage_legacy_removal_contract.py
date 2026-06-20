# harness/test_storage_legacy_removal_contract.py
"""Contract tests verifying legacy code has been removed from runtime."""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_new_workspace_does_not_create_files_upload(monkeypatch, tmp_path):
    ws = tmp_path / "workspaces"
    ws.mkdir()
    monkeypatch.setenv("NA_WORKSPACE_ROOT", str(ws))
    monkeypatch.setattr("workspace.manager.WS_ROOT", ws)

    from workspace.manager import ensure_workspace
    ensure_workspace("test_ws")

    assert not (ws / "test_ws" / "files" / "upload").exists()
    assert not (ws / "test_ws" / "files" / "agent").exists()


def test_runtime_has_no_legacy_tokens():
    """Runtime code must not contain tracking_only, legacy_artifact_store, etc."""
    from pathlib import Path

    roots = ["artifacts", "workspace", "agent", "backend", "storage"]
    # Allow these tokens in:
    # - legacy_migration.py (migration tool)
    # - test files (historical assertions)
    whitelist = {
        "storage/legacy_migration.py",
        "harness/test_storage_legacy_migration.py",
    }

    forbidden = [
        "tracking_only",
        "legacy_artifact_store",
    ]

    hits = []
    project_root = Path(__file__).resolve().parents[1]
    for root in roots:
        root_path = project_root / root
        if not root_path.exists():
            continue
        for p in root_path.rglob("*.py"):
            rel = str(p.relative_to(project_root))
            if any(rel.startswith(w) for w in whitelist):
                continue
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for token in forbidden:
                if token in text:
                    hits.append((rel, token))

    assert hits == [], f"Legacy tokens found in runtime: {hits}"


def test_knowledge_allowed_roots_excludes_legacy():
    from agent.modules.knowledge.ingestion import _allowed_import_roots

    roots = _allowed_import_roots("test_ws")
    root_paths = [str(r).replace("\\", "/") for r in roots]
    # Check for exact legacy directory matches (not substring in agent_output)
    for rp in root_paths:
        basename = rp.rstrip("/").split("/")[-2:]
        assert "files/upload" not in rp, f"Legacy path files/upload still in allowed roots"
        assert basename != ["files", "agent"], f"Legacy dir files/agent still in allowed roots"


def test_read_artifact_content_no_legacy_fallback():
    """Verify read_artifact_content no longer contains legacy path fallback."""
    project_root = Path(__file__).resolve().parents[1]
    path = project_root / "artifacts" / "store.py"
    text = path.read_text(encoding="utf-8")
    # The function should not have the old "Legacy path fallback" pattern
    assert "Legacy path fallback" not in text


def test_pcap_service_no_sidecar_fallback():
    """Verify PCAP service no longer references load_session_from_file."""
    project_root = Path(__file__).resolve().parents[1]
    path = project_root / "agent" / "modules" / "pcap" / "service.py"
    text = path.read_text(encoding="utf-8")
    assert "load_session_from_file" not in text
    assert "session_meta_path" not in text
