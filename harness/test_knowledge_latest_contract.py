from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (PROJECT_ROOT / path).read_text(encoding="utf-8")


def test_runtime_knowledge_paths_do_not_import_legacy_package():
    targets = [
        "backend/api/knowledge_routes.py",
        "agent/modules/knowledge/service.py",
        "tool_runtime/general_tools/runtime_tools.py",
    ]
    forbidden = [
        "from " + "knowledge.",
        "import " + "knowledge.",
        "context." + "knowledge_loader",
        "_query_via_compat_loader",
        "compat_",
        "_compat",
    ]
    for target in targets:
        text = _read(target)
        for needle in forbidden:
            assert needle not in text, f"{target} still contains {needle!r}"


def test_legacy_knowledge_surfaces_are_physically_removed():
    retired_paths = [
        "knowledge",
        "context/" + "knowledge_loader.py",
        "skills/" + "knowledge_search",
        "harness/test_knowledge_index_runtime.py",
    ]
    for path in retired_paths:
        assert not (PROJECT_ROOT / path).exists(), f"{path} should be removed"


def test_no_source_file_references_removed_knowledge_surfaces():
    scanned_roots = [
        "agent",
        "artifacts",
        "backend",
        "context",
        "frontend/src",
        "harness",
        "modules",
        "skills",
        "tool_runtime",
    ]
    forbidden = [
        "from " + "knowledge.",
        "import " + "knowledge.",
        "context." + "knowledge_loader",
        "skills/" + "knowledge_search",
        "skills." + "knowledge_search",
        "knowledge" + ".query",
        "tool_handler_" + "query",
        "TOOL_KNOWLEDGE_" + "QUERY",
    ]
    # New-architecture pipeline files legitimately reference knowledge querying
    new_pipeline_prefixes = (
        "agent/runtime/cognition/",
        "agent/runtime/knowledge/",
        "agent/runtime/memory/",
        "agent/runtime/context/",
    )
    # Test files that exercise the new pipeline and import from it
    new_pipeline_test_files = {
        "harness/test_context_memory_knowledge_refactor.py",
    }
    for root in scanned_roots:
        base = PROJECT_ROOT / root
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path == Path(__file__).resolve():
                continue
            if not path.is_file() or path.suffix not in {".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".yaml", ".yml", ".md"}:
                continue
            rel = path.relative_to(PROJECT_ROOT)
            rel_posix = rel.as_posix()
            if any(rel_posix.startswith(p) for p in new_pipeline_prefixes):
                continue
            if rel_posix in new_pipeline_test_files:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for needle in forbidden:
                assert needle not in text, f"{rel} still contains {needle!r}"


def test_knowledge_search_rejects_retired_query_params():
    from backend.main import app

    client = app.test_client()
    for param in ("artifact_type", "sensitivity", "artifact_id"):
        resp = client.get(
            "/api/knowledge/search",
            query_string={"workspace_id": "default", "q": "ospf", param: "legacy"},
        )
        assert resp.status_code == 400
        body = resp.get_json()
        assert body["error"] == "retired_query_params"
        assert param in body["retired_params"]


def test_frontend_knowledge_search_does_not_send_retired_artifact_filter():
    text = _read("frontend/src/api/index.ts")
    search_block = text.split("search: (", 1)[1].split("getChunk:", 1)[0]
    assert "artifact_id" not in search_block
    assert "artifact_type" not in search_block
    assert "sensitivity" not in search_block


def test_llm_tool_catalog_no_longer_exposes_retired_knowledge_query():
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
        old_tool_id = "knowledge" + ".query"
        assert old_tool_id not in _read(target), f"{target} still exposes {old_tool_id}"


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
