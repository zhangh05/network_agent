# harness/test_backend_final_cutover_contract.py
"""Final backend cutover contract — real behavior tests."""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def final_ws(monkeypatch, tmp_path):
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


def test_canonical_registry_registers_file_tools():
    """canonical_registry MUST register all 5 FileStore tools."""
    from tool_runtime.canonical_registry import CANONICAL_REGISTRY
    required = [
        "file.get",
        "file.preview",
        "file.references",
        "file.write_agent_output",
        "file.import_workspace_path",
    ]
    for tid in required:
        assert tid in CANONICAL_REGISTRY, f"Missing canonical tool: {tid}"


def test_canonical_registry_imports_registry_helpers():
    """canonical_registry MUST import registry_helpers."""
    import tool_runtime.canonical_registry as cr
    assert hasattr(cr, "tool_keyword_score"), "registry_helpers not imported in canonical_registry"


def test_filestore_tools_read_real_file(final_ws):
    """file.get handler MUST read text content from FileStore."""
    from storage.file_store import write_agent_output
    from tool_runtime.general_tools.filestore_tools import handle_file_get, handle_file_preview

    rec = write_agent_output("test_ws", "hello from filestore tool", "artifact_output", "text", title="ft test")

    class FakeInv:
        workspace_id = "test_ws"
    result = handle_file_get(FakeInv(), file_id=rec.file_id)
    assert result["ok"] is True
    assert "hello from filestore tool" in result["content"]
    assert result["file_id"] == rec.file_id

    preview = handle_file_preview(FakeInv(), file_id=rec.file_id)
    assert preview["ok"] is True
    assert preview["file_kind"] == "text"


def test_filestore_tools_write_agent_output(final_ws):
    """file.write_agent_output handler MUST create FileRecord."""
    from tool_runtime.general_tools.filestore_tools import handle_file_write_agent_output

    class FakeInv:
        workspace_id = "test_ws"
    result = handle_file_write_agent_output(
        FakeInv(), content="agent output test", logical_type="report", file_kind="text",
        title="test report", ext="txt",
    )
    assert result["ok"] is True
    assert result["file_id"].startswith("file_")
    assert result["size_bytes"] > 0


def test_reference_api_returns_real_data(final_ws, monkeypatch):
    """Reference API MUST return real data when references exist."""
    monkeypatch.setattr("workspace.manager.WS_ROOT", final_ws)
    monkeypatch.setenv("NA_WORKSPACE_ROOT", str(final_ws))

    from storage.file_store import write_agent_output
    from storage.reference_index import add_reference
    from backend.main import app

    rec = write_agent_output("test_ws", "ref test", "artifact_output", "text", title="ref test")
    add_reference("test_ws", rec.file_id, "artifact", "art_ref_test", "output")

    client = app.test_client()
    resp = client.get(f"/api/workspaces/test_ws/files/{rec.file_id}/references")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["count"] >= 1
    assert any(r["owner_type"] == "artifact" for r in body["references"])


def test_gc_script_exists_and_importable():
    """GC script MUST exist."""
    script = Path(__file__).resolve().parents[1] / "scripts" / "storage_gc.py"
    assert script.exists()
    # Verify it runs as a module
    from scripts.storage_gc import run_gc_dry_run


def test_legacy_files_agent_not_in_runtime():
    """Runtime code MUST NOT reference legacy paths."""
    root = Path(__file__).resolve().parents[1]
    runtime_dirs = ["artifacts", "workspace", "agent", "backend", "storage", "tool_runtime"]
    exempt = ["storage/legacy_migration.py", "scripts/storage_legacy_migrate.py"]
    hits = []
    for rd in runtime_dirs:
        for py_file in (root / rd).rglob("*.py"):
            rel = str(py_file.relative_to(root))
            if any(rel.startswith(e) or rel == e for e in exempt):
                continue
            text = py_file.read_text(encoding="utf-8", errors="ignore")
            if "legacy_artifact_store" in text or "tracking_only" in text:
                hits.append(rel)
    assert hits == [], f"Legacy tokens found: {hits}"
