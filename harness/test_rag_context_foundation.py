import io


def _client():
    from backend.main import app
    app.testing = True
    return app.test_client()


def _patch_ws_roots(tmp_path, monkeypatch):
    from artifacts import store as artifact_store
    from agent.modules.knowledge import ingestion
    import workspace.manager as workspace_manager

    ws_root = tmp_path / "workspaces"
    monkeypatch.setattr(artifact_store, "WS_ROOT", ws_root)
    monkeypatch.setattr(workspace_manager, "WS_ROOT", ws_root)
    monkeypatch.setattr(ingestion, "_ws_root", lambda: ws_root)
    return ws_root


def test_knowledge_upload_markdown_indexes_source(tmp_path, monkeypatch):
    _patch_ws_roots(tmp_path, monkeypatch)

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
    _patch_ws_roots(tmp_path, monkeypatch)

    client = _client()
    resp = client.post("/api/knowledge/upload", data={"workspace_id": "rag_ws"})

    assert resp.status_code == 400
    assert resp.get_json()["error"] == "no file provided"


def test_knowledge_upload_is_visible_to_sources_and_search(tmp_path, monkeypatch):
    _patch_ws_roots(tmp_path, monkeypatch)

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
    from agent.modules.knowledge.service import import_file

    _patch_ws_roots(tmp_path, monkeypatch)
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


def _isolated_memory_store(tmp_path, monkeypatch):
    from memory.backends.jsonl_store import JSONLMemoryStore
    import memory.store as memory_store

    store = JSONLMemoryStore(str(tmp_path / "memory"))
    monkeypatch.setattr(memory_store, "_store", store)
    return store


def test_memory_write_creates_rag_projection(tmp_path, monkeypatch):
    _patch_ws_roots(tmp_path, monkeypatch)
    _isolated_memory_store(tmp_path, monkeypatch)

    from memory.writer import write_user_preference
    from agent.modules.knowledge.service import query_knowledge

    memory_id = write_user_preference(
        title="默认厂商偏好",
        content="用户偏好：默认使用华为 VRP 命令格式回答网络配置问题。",
        tags=["preference", "vendor"],
        project_id="rag_ws",
    )

    assert memory_id
    result = query_knowledge(
        query="默认使用什么厂商命令格式",
        workspace_id="rag_ws",
        top_k=3,
        filters={"source_type": "memory"},
    )

    assert result["hits"]
    assert result["hits"][0]["metadata"]["source_type"] == "memory"
    assert "华为 VRP" in str(result["hits"])


def test_context_loader_uses_rag_memory_projection(tmp_path, monkeypatch):
    _patch_ws_roots(tmp_path, monkeypatch)
    _isolated_memory_store(tmp_path, monkeypatch)

    from memory.writer import write_user_confirmed_decision
    from context.loader import load_context_items

    memory_id = write_user_confirmed_decision(
        title="出口策略决策",
        content="本项目出口策略优先使用主备链路，不采用 ECMP。",
        tags=["egress", "policy"],
        project_id="rag_ws",
    )

    assert memory_id
    items = load_context_items("rag_ws", user_input="出口策略是否采用 ECMP")
    memory_rag = [
        i for i in items
        if i.item_type == "knowledge_chunk"
        and i.content.get("source_type") == "memory"
    ]

    assert memory_rag
    assert "不采用 ECMP" in str(memory_rag[0].content)


def test_unified_retrieval_returns_document_and_memory_sources(tmp_path, monkeypatch):
    _seed_knowledge(tmp_path, monkeypatch)
    _isolated_memory_store(tmp_path, monkeypatch)

    from memory.writer import write_user_preference
    from context.retrieval import retrieve_context_evidence

    memory_id = write_user_preference(
        title="回答风格偏好",
        content="用户偏好：回答 OSPF 排查问题时先给最短命令顺序。",
        tags=["ospf", "style"],
        project_id="rag_ws",
    )
    assert memory_id

    result = retrieve_context_evidence("rag_ws", "OSPF FULL 变 INIT 怎么排查")
    evidence_types = {s["evidence_type"] for s in result["sources"]}

    assert result["ok"] is True
    assert "knowledge" in evidence_types
    assert "memory" in evidence_types
    assert result["diagnostics"]["query_variants"]


def test_context_bundle_exposes_context_sources_for_ui(tmp_path, monkeypatch):
    _seed_knowledge(tmp_path, monkeypatch)
    _isolated_memory_store(tmp_path, monkeypatch)

    from memory.writer import write_user_preference
    from context.builder import build_context_bundle
    from agent.runtime.loop import _enrich_metadata

    write_user_preference(
        title="OSPF 输出偏好",
        content="用户偏好：OSPF 故障回答要先列检查命令。",
        tags=["ospf"],
        project_id="rag_ws",
    )

    bundle = build_context_bundle("rag_ws", user_input="OSPF FULL 变 INIT")
    safe = bundle.safe_llm_context
    metadata = _enrich_metadata({}, type("Ctx", (), {"metadata": {}, "safe_context": safe.as_dict()})())

    assert safe.context_sources
    assert metadata["context_sources"]
    assert metadata["source_summary"]
    assert metadata["source_count"] == len(metadata["context_sources"])


def test_memory_delete_removes_rag_projection(tmp_path, monkeypatch):
    _patch_ws_roots(tmp_path, monkeypatch)
    _isolated_memory_store(tmp_path, monkeypatch)

    from agent.modules.knowledge.service import query_knowledge

    client = _client()
    written = client.post("/api/memory/confirm", json={
        "memory_type": "decision",
        "title": "安全边界决策",
        "content": "本项目不允许把生产密钥写入知识库。",
        "tags": ["security"],
        "project_id": "rag_ws",
    })
    assert written.status_code == 200
    memory_id = written.get_json()["memory_id"]

    before = query_knowledge(
        query="生产密钥是否允许写入知识库",
        workspace_id="rag_ws",
        top_k=3,
        filters={"source_type": "memory"},
    )
    assert before["hits"]

    deleted = client.delete(f"/api/memory/{memory_id}")
    assert deleted.status_code == 200
    assert deleted.get_json()["ok"] is True

    after = query_knowledge(
        query="生产密钥是否允许写入知识库",
        workspace_id="rag_ws",
        top_k=3,
        filters={"source_type": "memory"},
    )
    assert after["hits"] == []


def test_memory_projection_is_hidden_from_public_knowledge_api(tmp_path, monkeypatch):
    _patch_ws_roots(tmp_path, monkeypatch)
    _isolated_memory_store(tmp_path, monkeypatch)

    from memory.writer import write_user_preference

    memory_id = write_user_preference(
        title="显示偏好",
        content="用户偏好：回答默认保持简洁。",
        tags=["style"],
        project_id="rag_ws",
    )
    assert memory_id

    client = _client()
    sources = client.get("/api/knowledge/sources?workspace_id=rag_ws").get_json()
    assert sources["sources"] == []
    assert sources["counts"]["indexed"] == 0

    search = client.get("/api/knowledge/search?workspace_id=rag_ws&q=默认保持简洁").get_json()
    assert search["results"] == []
