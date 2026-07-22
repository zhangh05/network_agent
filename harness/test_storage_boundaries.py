"""Current storage boundary contracts."""

from pathlib import Path
import io
import ast
import subprocess
import sys
import time
import threading


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


def test_data_center_overview_and_content_use_filestore_as_source_of_truth(monkeypatch, tmp_path):
    root = tmp_path / "workspaces"
    monkeypatch.setenv("NA_WORKSPACE_ROOT", str(root))
    from storage.file_store import write_agent_output
    from backend.main import app

    record = write_agent_output(
        "data_center_ws", "interface status up", "report", "text", title="status.txt",
    )
    client = app.test_client()
    overview = client.get("/api/storage/overview", query_string={"workspace_id": "data_center_ws"})
    assert overview.status_code == 200
    assert overview.get_json()["overview"]["files"] == {
        "total": 1,
        "active": 1,
        "archived": 0,
        "soft_deleted": 0,
        "size_bytes": len("interface status up"),
        "referenced": 0,
        "unreferenced": 1,
    }
    content = client.get(
        f"/api/storage/files/{record.file_id}/content",
        query_string={"workspace_id": "data_center_ws"},
    )
    assert content.status_code == 200
    assert content.get_json()["content"] == "interface status up"


def test_data_center_refuses_to_delete_referenced_files(monkeypatch, tmp_path):
    root = tmp_path / "workspaces"
    monkeypatch.setenv("NA_WORKSPACE_ROOT", str(root))
    from storage.file_store import get_file_record, write_agent_output
    from storage.reference_index import add_reference
    from backend.main import app

    record = write_agent_output(
        "protected_data_ws", "important", "report", "text", title="protected.txt",
    )
    add_reference("protected_data_ws", record.file_id, "run", "run-1")
    response = app.test_client().delete(
        f"/api/storage/files/{record.file_id}",
        query_string={"workspace_id": "protected_data_ws", "confirm": "true"},
    )
    assert response.status_code == 409
    assert response.get_json()["error"] == "file_in_use"
    assert get_file_record("protected_data_ws", record.file_id) is not None


def test_data_center_permanently_deletes_standalone_files(monkeypatch, tmp_path):
    root = tmp_path / "workspaces"
    monkeypatch.setenv("NA_WORKSPACE_ROOT", str(root))
    from storage.file_store import get_file_record, write_agent_output
    from backend.main import app

    record = write_agent_output(
        "standalone_data_ws", "disposable", "report", "text", title="temporary.txt",
    )
    response = app.test_client().delete(
        f"/api/storage/files/{record.file_id}",
        query_string={"workspace_id": "standalone_data_ws", "confirm": "true"},
    )
    assert response.status_code == 200
    assert get_file_record("standalone_data_ws", record.file_id) is None


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


def test_runtime_records_live_under_runtime_root(monkeypatch, tmp_path):
    monkeypatch.setenv("NA_WORKSPACE_ROOT", str(tmp_path / "workspaces"))
    from storage.records import runtime_record_file

    path = runtime_record_file("approvals", "tool_approvals.jsonl")

    assert path == tmp_path / "workspaces" / "_runtime" / "approvals" / "tool_approvals.jsonl"


def test_approval_default_store_does_not_use_root_data(monkeypatch, tmp_path):
    monkeypatch.setenv("NA_WORKSPACE_ROOT", str(tmp_path / "workspaces"))
    import agent.approval as approval_module
    from agent.approval import ApprovalStore

    monkeypatch.setattr(approval_module, "_APPROVALS_FILE", None)
    store = ApprovalStore()
    store.create(
        session_id="sess_1",
        tool_id="exec.run",
        arguments={"cmd": "rm -rf /tmp/nope"},
        description="dangerous",
        risk_level="high",
        workspace_id="approval_ws",
    )

    assert store._persist_path == tmp_path / "workspaces" / "_runtime" / "approvals" / "tool_approvals.jsonl"
    assert store._persist_path.is_file()
    assert not (Path(__file__).resolve().parents[1] / "data" / "tool_approvals.jsonl").exists()


def test_consolidated_modules_do_not_reintroduce_ad_hoc_jsonl_io():
    project_root = Path(__file__).resolve().parents[1]
    targets = [
        "agent/approval.py",
        "agent/runtime/token_tracker.py",
        "core/context/context_store.py",
        "observability/store.py",
        "storage/reference_index.py",
        "storage/session_snapshot.py",
    ]
    forbidden = ("with open(", ".open(\"a", ".open('a", "write_text(", "os.replace(")
    violations = []
    for rel in targets:
        text = (project_root / rel).read_text(encoding="utf-8")
        for marker in forbidden:
            if marker in text:
                violations.append(f"{rel}: {marker}")

    assert violations == []


def test_record_reads_do_not_create_workspace_directories(monkeypatch, tmp_path):
    monkeypatch.setenv("NA_WORKSPACE_ROOT", str(tmp_path / "workspaces"))
    from storage.records import list_json_records, read_json_record, read_jsonl

    assert read_jsonl("ghost", ("context", "items.jsonl")) == []
    assert read_json_record("ghost", ("runs", "missing.json")) is None
    assert list_json_records("ghost", ("durable", "tasks")) == []
    assert not (tmp_path / "workspaces" / "ghost").exists()


def test_file_lock_timeout_fails_closed_across_processes(tmp_path):
    lock_path = tmp_path / "cross_process.lock"
    code = (
        "import sys,time; from pathlib import Path; "
        "from storage.locking import FileLock; "
        "c=FileLock(Path(sys.argv[1]),timeout=2); c.__enter__(); "
        "print('locked',flush=True); time.sleep(3); c.__exit__(None,None,None)"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", code, str(lock_path)],
        cwd=str(Path(__file__).resolve().parents[1]),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout.readline().strip() == "locked"
        from storage.locking import FileLock
        started = time.monotonic()
        try:
            with FileLock(lock_path, timeout=0.15, retry_interval=0.01):
                raise AssertionError("contender entered a locked critical section")
        except TimeoutError:
            pass
        assert time.monotonic() - started >= 0.1
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_storage_services_use_domain_repositories():
    project_root = Path(__file__).resolve().parents[1]
    targets = [
        "agent/modules/cmdb/service.py",
        "agent/modules/remote/service.py",
        "agent/runtime/token_tracker.py",
        "agent/runtime/durable/delivery.py",
        "agent/runtime/durable/trajectory.py",
        "agent/runtime/durable/subagent.py",
        "core/tools/python_exec.py",
    ]
    forbidden = {"storage.paths", "storage.records", "storage.atomic_io"}
    violations = []
    for rel in targets:
        tree = ast.parse((project_root / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "") in forbidden:
                violations.append(f"{rel}: {node.module}")
    assert violations == []


def test_agent_and_backend_do_not_import_low_level_storage_adapters():
    project_root = Path(__file__).resolve().parents[1]
    forbidden = {"storage.paths", "storage.records", "storage.atomic_io"}
    violations = []
    for root_name in ("agent", "backend"):
        for path in (project_root / root_name).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and (node.module or "") in forbidden:
                    violations.append(f"{path.relative_to(project_root)}: {node.module}")
    assert violations == []


def test_jsonl_mutation_serializes_concurrent_append(monkeypatch, tmp_path):
    monkeypatch.setenv("NA_WORKSPACE_ROOT", str(tmp_path / "workspaces"))
    from storage.records import append_jsonl, mutate_jsonl, read_jsonl

    parts = ("index", "references.jsonl")
    append_jsonl("ws", parts, {"ref_id": "first"})
    entered = threading.Event()
    release = threading.Event()

    def mutate():
        def callback(rows):
            entered.set()
            assert release.wait(timeout=2)
            return rows, None
        mutate_jsonl("ws", parts, callback)

    writer_done = threading.Event()
    t1 = threading.Thread(target=mutate)
    t1.start()
    assert entered.wait(timeout=2)
    t2 = threading.Thread(target=lambda: (
        append_jsonl("ws", parts, {"ref_id": "second"}), writer_done.set()
    ))
    t2.start()
    time.sleep(0.05)
    assert not writer_done.is_set()
    release.set()
    t1.join(timeout=2)
    t2.join(timeout=2)

    assert [row["ref_id"] for row in read_jsonl("ws", parts)] == ["first", "second"]


def test_jsonl_mutation_refuses_to_erase_malformed_records(monkeypatch, tmp_path):
    monkeypatch.setenv("NA_WORKSPACE_ROOT", str(tmp_path / "workspaces"))
    from storage.records import mutate_jsonl, workspace_record_file

    parts = ("index", "references.jsonl")
    path = workspace_record_file("ws", *parts)
    original = '{"ref_id":"valid"}\nnot-json\n'
    path.write_text(original, encoding="utf-8")

    try:
        mutate_jsonl("ws", parts, lambda rows: (rows, None))
        raise AssertionError("malformed JSONL mutation unexpectedly succeeded")
    except ValueError as exc:
        assert "malformed_jsonl_record" in str(exc)
    assert path.read_text(encoding="utf-8") == original


def test_workspace_credential_key_is_atomic_under_threads(monkeypatch, tmp_path):
    monkeypatch.setenv("NA_WORKSPACE_ROOT", str(tmp_path / "workspaces"))
    from storage.credential_store import open_credential_strict, seal_credential

    sealed: list[str] = []
    threads = [
        threading.Thread(target=lambda value=f"secret-{i}": sealed.append(seal_credential("ws", value)))
        for i in range(12)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=3)

    assert len(sealed) == 12
    assert {open_credential_strict("ws", value) for value in sealed} == {
        f"secret-{i}" for i in range(12)
    }
    key = tmp_path / "workspaces" / "ws" / "cmdb" / ".credential_key"
    assert key.stat().st_size == 32
