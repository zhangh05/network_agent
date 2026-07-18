"""Current storage boundary contracts."""

from pathlib import Path
import io
import ast


def test_new_workspace_creates_current_storage_dirs(monkeypatch, tmp_path):
    ws = tmp_path / "workspaces"
    ws.mkdir()
    monkeypatch.setenv("NA_WORKSPACE_ROOT", str(ws))

    from storage.workspace_store import ensure_workspace

    ensure_workspace("test_ws")

    assert (ws / "test_ws" / "files" / "data").is_dir()
    assert (ws / "test_ws" / "files" / "tmp").is_dir()


def test_knowledge_allowed_roots_use_current_storage():
    from agent.modules.knowledge.ingestion import _allowed_import_roots

    roots = _allowed_import_roots("test_ws")
    root_paths = [str(r).replace("\\", "/") for r in roots]
    assert any(path.endswith("/files/data") for path in root_paths)


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


def test_storage_api_projects_managed_files_without_paths(monkeypatch, tmp_path):
    root = tmp_path / "workspaces"
    monkeypatch.setenv("NA_WORKSPACE_ROOT", str(root))
    from storage.file_store import write_agent_output
    from backend.main import app

    record = write_agent_output(
        "storage_api_ws", "payload", "report", "text", title="report",
    )
    response = app.test_client().get(
        "/api/storage/files",
        query_string={"workspace_id": "storage_api_ws"},
    )
    assert response.status_code == 200
    files = response.get_json()["files"]
    assert files[0]["file_id"] == record.file_id
    assert files[0]["logical_type"] == "report"
    assert "path" not in files[0]


def test_text_artifact_upload_reuses_one_file_record(monkeypatch, tmp_path):
    root = tmp_path / "workspaces"
    monkeypatch.setenv("NA_WORKSPACE_ROOT", str(root))
    import artifacts.store as artifact_store
    from backend.main import app
    from storage.file_store import list_files

    response = app.test_client().post(
        "/api/workspaces/upload_ws/artifacts/upload",
        data={
            "file": (io.BytesIO(b"plain operational notes"), "notes.txt"),
            "artifact_type": "text",
            "title": "Notes",
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["artifact"] is not None
    active = list_files("upload_ws")
    assert len(active) == 1
    assert active[0]["file_id"] == body["artifact"]["file_id"]


def test_storage_layer_has_no_control_plane_imports():
    project_root = Path(__file__).resolve().parents[1]
    forbidden = {"agent", "artifacts", "backend", "core", "jobs"}
    violations: list[str] = []
    for path in sorted((project_root / "storage").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            module = ""
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                module = name.split(".", 1)[0]
                if module in forbidden:
                    violations.append(f"{path.relative_to(project_root)} imports {name}")
    assert violations == []


def test_jsonl_transaction_is_reentrant(monkeypatch, tmp_path):
    monkeypatch.setenv("NA_WORKSPACE_ROOT", str(tmp_path / "workspaces"))
    from storage.records import append_jsonl, jsonl_transaction, read_jsonl, rewrite_jsonl

    parts = ("cmdb", "assets.jsonl")
    append_jsonl("lock_ws", parts, {"asset_id": "a1", "name": "PE1"})
    with jsonl_transaction("lock_ws", parts):
        rows = read_jsonl("lock_ws", parts)
        rows.append({"asset_id": "a2", "name": "PE2"})
        rewrite_jsonl("lock_ws", parts, rows)

    assert [row["asset_id"] for row in read_jsonl("lock_ws", parts)] == ["a1", "a2"]
