import io


def _client():
    from backend.main import app
    app.testing = True
    return app.test_client()


def test_knowledge_upload_markdown_indexes_source(tmp_path, monkeypatch):
    from artifacts import store as artifact_store
    from agent.modules.knowledge import ingestion
    import workspace.manager as workspace_manager

    ws_root = tmp_path / "workspaces"
    monkeypatch.setattr(artifact_store, "WS_ROOT", ws_root)
    monkeypatch.setattr(workspace_manager, "WS_ROOT", ws_root)
    monkeypatch.setattr(ingestion, "_ws_root", lambda: ws_root)

    client = _client()
    data = {
        "workspace_id": "rag_ws",
        "title": "OSPF Runbook",
        "tags": "ospf,runbook",
        "file": (io.BytesIO(b"# OSPF\n\nFULL to INIT often means one-way hello."), "ospf.md"),
    }
    resp = client.post("/api/knowledge/upload", data=data, content_type="multipart/form-data")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["source"]["source_id"]
    assert body["source"]["title"] == "OSPF Runbook"
    assert body["source"]["chunk_count"] > 0
    assert "/Users/" not in str(body)
    assert str(tmp_path) not in str(body)


def test_knowledge_upload_requires_file(tmp_path, monkeypatch):
    from artifacts import store as artifact_store
    from agent.modules.knowledge import ingestion
    import workspace.manager as workspace_manager

    ws_root = tmp_path / "workspaces"
    monkeypatch.setattr(artifact_store, "WS_ROOT", ws_root)
    monkeypatch.setattr(workspace_manager, "WS_ROOT", ws_root)
    monkeypatch.setattr(ingestion, "_ws_root", lambda: ws_root)

    client = _client()
    resp = client.post("/api/knowledge/upload", data={"workspace_id": "rag_ws"})

    assert resp.status_code == 400
    assert resp.get_json()["error"] == "no file provided"


def test_knowledge_upload_is_visible_to_sources_and_search(tmp_path, monkeypatch):
    from artifacts import store as artifact_store
    from agent.modules.knowledge import ingestion
    import workspace.manager as workspace_manager

    ws_root = tmp_path / "workspaces"
    monkeypatch.setattr(artifact_store, "WS_ROOT", ws_root)
    monkeypatch.setattr(workspace_manager, "WS_ROOT", ws_root)
    monkeypatch.setattr(ingestion, "_ws_root", lambda: ws_root)

    client = _client()
    upload = client.post(
        "/api/knowledge/upload",
        data={
            "workspace_id": "rag_ws",
            "title": "OSPF Runbook",
            "file": (io.BytesIO(b"# OSPF\n\nFULL to INIT often means one-way hello."), "ospf.md"),
        },
        content_type="multipart/form-data",
    )
    assert upload.status_code == 200

    sources = client.get("/api/knowledge/sources?workspace_id=rag_ws").get_json()
    assert sources["counts"]["indexed"] == 1
    assert sources["sources"][0]["title"] == "OSPF Runbook"

    search = client.get("/api/knowledge/search?workspace_id=rag_ws&q=OSPF").get_json()
    assert search["count"] >= 1
    assert "one-way hello" in search["results"][0]["safe_excerpt"]


def _seed_knowledge(tmp_path, monkeypatch):
    from artifacts import store as artifact_store
    from agent.modules.knowledge import ingestion
    from agent.modules.knowledge.service import import_file
    import workspace.manager as workspace_manager

    ws_root = tmp_path / "workspaces"
    monkeypatch.setattr(artifact_store, "WS_ROOT", ws_root)
    monkeypatch.setattr(workspace_manager, "WS_ROOT", ws_root)
    monkeypatch.setattr(ingestion, "_ws_root", lambda: ws_root)
    result = import_file(
        workspace_id="rag_ws",
        source=b"# OSPF\n\nFULL to INIT often means one-way hello.",
        title="OSPF Runbook",
        source_type="project_doc",
        scope="workspace",
        tags=["ospf"],
    )
    assert result["ok"] is True


def test_context_loader_adds_knowledge_chunks(tmp_path, monkeypatch):
    _seed_knowledge(tmp_path, monkeypatch)
    from context.loader import load_context_items

    items = load_context_items("rag_ws", user_input="FULL 变 INIT 是什么原因")

    knowledge = [i for i in items if i.item_type == "knowledge_chunk"]
    assert knowledge
    assert "one-way hello" in str(knowledge[0].content)
    assert "source_config" not in str(knowledge[0].content)


def test_context_bundle_exposes_knowledge_hits_and_citations(tmp_path, monkeypatch):
    _seed_knowledge(tmp_path, monkeypatch)
    from context.builder import build_context_bundle

    bundle = build_context_bundle("rag_ws", user_input="FULL 变 INIT 是什么原因")
    safe = bundle.safe_llm_context

    assert safe.knowledge_hits
    assert safe.citations
    assert safe.citations[0]["citation_id"] == "K1"


def test_initial_messages_include_knowledge_hits(tmp_path, monkeypatch):
    _seed_knowledge(tmp_path, monkeypatch)
    from types import SimpleNamespace
    from agent.context.snapshot import RuntimeSnapshot
    from agent.runtime.loop import _build_initial_messages
    from context.builder import build_context_bundle

    bundle = build_context_bundle("rag_ws", user_input="FULL 变 INIT 是什么原因")
    safe_context = bundle.safe_llm_context.as_dict()
    ctx = SimpleNamespace(
        runtime_snapshot=RuntimeSnapshot().to_dict(),
        workspace_id="rag_ws",
        session_id="session_0",
        model_config={"model": "MiniMax-M3"},
        history_window=[],
        user_input="FULL 变 INIT 是什么原因",
        skill_snapshot={},
        safe_context=safe_context,
    )

    messages = _build_initial_messages(ctx, services=None)
    joined = "\n".join(m.content for m in messages)
    assert "knowledge_hits" in joined
    assert "one-way hello" in joined
    assert "K1" in joined
