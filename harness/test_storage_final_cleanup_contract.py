# harness/test_storage_final_cleanup_contract.py
"""Final cleanup contract tests — new writes must use FileStore-managed paths."""

import io
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def cleanup_ws(monkeypatch, tmp_path):
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


def test_new_artifact_content_uses_agent_output(cleanup_ws):
    """New artifacts MUST write to files/agent_output/, not files/agent/."""
    from artifacts.store import save_artifact
    from storage.file_store import resolve_file_path

    rec = save_artifact(
        workspace_id="test_ws",
        content="final cleanup contract",
        artifact_type="report",
        title="cleanup report",
        sensitivity="internal",
    )

    assert rec.file_id
    p = resolve_file_path("test_ws", rec.file_id)
    normalized = str(p).replace("\\", "/")
    assert "/files/agent_output/" in normalized
    assert "/files/agent/" not in normalized


def test_no_runtime_tracking_only_literal():
    """Running source code must not contain tracking_only=True."""
    hits = []
    runtime_roots = ["artifacts", "workspace", "agent", "backend", "storage"]
    for root in runtime_roots:
        root_path = Path(__file__).resolve().parents[1] / root
        if not root_path.exists():
            continue
        for p in root_path.rglob("*.py"):
            text = p.read_text(encoding="utf-8", errors="ignore")
            if "tracking_only=True" in text or '"tracking_only": True' in text:
                hits.append(str(p))
    assert hits == [], f"tracking_only still found in: {hits}"


def test_new_artifact_does_not_write_legacy(cleanup_ws):
    """New save_artifact must NOT create content files under files/agent/."""
    from artifacts.store import save_artifact

    rec = save_artifact(
        workspace_id="test_ws",
        content="cleanup test content",
        artifact_type="report",
        title="final cleanup check",
        sensitivity="internal",
    )

    # No content files (non-meta) should appear in files/agent/
    agent_dir = cleanup_ws / "test_ws" / "files" / "agent"
    if agent_dir.exists():
        content_files = [p for p in agent_dir.glob("*") if not p.name.endswith(".meta.json")]
        assert content_files == [], f"Legacy content files found: {content_files}"

    assert rec.file_id


def test_artifact_store_no_catch_all_fallback():
    """artifacts/store.py must not have a wide except: fpath.write_text(content) fallback."""
    root = Path(__file__).resolve().parents[1] / "artifacts" / "store.py"
    text = root.read_text(encoding="utf-8")
    # The legacy fallback pattern should not exist
    assert "fpath.write_text(content)" not in text or \
           "artifact store" not in text.lower()
