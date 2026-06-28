from pathlib import Path
import io


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


def test_current_knowledge_surfaces_exist():
    current_paths = [
        "agent/modules/knowledge",
        "agent/runtime/knowledge",
        "backend/api/knowledge_routes.py",
    ]
    for path in current_paths:
        assert (PROJECT_ROOT / path).exists(), f"{path} should exist"


def test_knowledge_search_rejects_unknown_query_params():
    from backend.main import app

    client = app.test_client()
    resp = client.get(
        "/api/knowledge/search",
        query_string={"workspace_id": "default", "q": "ospf", "unsupported": "value"},
    )
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["error"] == "invalid_query_params"
    assert body["invalid_params"] == ["unsupported"]


def test_knowledge_upload_writes_through_filestore(monkeypatch, tmp_path):
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    monkeypatch.setenv("NA_WORKSPACE_ROOT", str(workspace_root))
    monkeypatch.setenv("NETWORK_AGENT_WORKSPACE_DIR", str(workspace_root))

    from backend.main import app
    from storage.file_store import list_files

    client = app.test_client()
    resp = client.post(
        "/api/knowledge/upload",
        data={
            "workspace_id": "default",
            "file": (io.BytesIO(b"# OSPF\nneighbor state"), "ospf.md"),
        },
        content_type="multipart/form-data",
    )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    files = list_files("default", lifecycle="")
    assert len(files) == 1
    assert files[0]["logical_type"] == "knowledge_source"
    assert files[0]["path"].startswith("files/knowledge/source/")


def test_frontend_knowledge_search_uses_current_query_contract():
    text = _read("frontend/src/api/index.ts")
    search_block = text.split("search: (", 1)[1].split("getChunk:", 1)[0]
    assert "workspace_id" in search_block
    assert "q:" in search_block
    assert "limit" in search_block


def test_llm_tool_catalog_exposes_current_knowledge_search():
    targets = [
        "agent/modules/knowledge/capability.py",
        "agent/modules/knowledge/tools.py",
        "tool_runtime/canonical_registry.py",
        "tool_runtime/tool_namespace_data.py",
        "tool_runtime/capability_actions.py",
        "agent/runtime/tool_category_router.py",
        "agent/runtime/sub_agent.py",
    ]
    for target in targets:
        text = _read(target)
        if target in {"agent/modules/knowledge/tools.py", "tool_runtime/canonical_registry.py"}:
            assert "knowledge.manage" in text


def test_import_from_artifact_uses_current_store_and_is_searchable(tmp_path, monkeypatch):
    from artifacts import store as artifact_store
    from workspace import manager as workspace_manager
    from artifacts.store import save_artifact
    from backend.main import app

    ws_root = tmp_path / "workspaces"
    monkeypatch.setattr(artifact_store, "WS_ROOT", ws_root)
    monkeypatch.setattr(workspace_manager, "WS_ROOT", ws_root)
    monkeypatch.setenv("NA_WORKSPACE_ROOT", str(ws_root))

    rec = save_artifact(
        "latest_knowledge_ws",
        content="OSPF neighbor jitter runbook: check one-way hello and MTU mismatch.",
        artifact_type="knowledge_doc",
        title="OSPF Jitter Runbook",
        sensitivity="internal",
        scope="workspace",
    )

    client = app.test_client()
    import_resp = client.post(
        "/api/knowledge/sources/from-artifact",
        json={"workspace_id": "latest_knowledge_ws", "artifact_id": rec.artifact_id},
    )
    assert import_resp.status_code == 200
    imported = import_resp.get_json()
    assert imported["source"]["source_id"].startswith("ksrc_")

    search_resp = client.get(
        "/api/knowledge/search",
        query_string={"workspace_id": "latest_knowledge_ws", "q": "OSPF neighbor"},
    )
    assert search_resp.status_code == 200
    body = search_resp.get_json()
    assert body["count"] >= 1
    assert "OSPF" in body["results"][0]["safe_excerpt"]
    assert body["results"][0]["artifact_id"] == rec.artifact_id
