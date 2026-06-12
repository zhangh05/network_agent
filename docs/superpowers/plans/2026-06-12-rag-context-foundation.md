# RAG Context Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a workspace-scoped RAG foundation so users can upload local documents to the knowledge library and the main `/api/agent/message` RuntimeLoop can retrieve safe knowledge excerpts as context.

**Architecture:** Reuse the existing file-based knowledge parser/chunker/index pipeline. Add a direct upload API and frontend upload panel, then make `context.loader` produce `knowledge_chunk` items that flow into `SafeLLMContext`, RuntimeLoop safe context, and UI inspector references.

**Tech Stack:** Flask, React/Vite/TypeScript, pytest harness, existing `agent.modules.knowledge` services, file-based workspace stores.

---

### Task 1: Backend Knowledge Upload API

**Files:**
- Modify: `backend/api/knowledge_routes.py`
- Test: `harness/test_rag_context_foundation.py`

- [ ] **Step 1: Write the failing upload tests**

Create `harness/test_rag_context_foundation.py` with:

```python
import io


def _client():
    from backend.main import app
    app.testing = True
    return app.test_client()


def test_knowledge_upload_markdown_indexes_source(tmp_path, monkeypatch):
    from artifacts import store as artifact_store
    from agent.modules.knowledge import ingestion
    monkeypatch.setattr(artifact_store, "WS_ROOT", tmp_path / "workspaces")
    monkeypatch.setattr(ingestion, "_ws_root", lambda: tmp_path / "workspaces")

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
    monkeypatch.setattr(artifact_store, "WS_ROOT", tmp_path / "workspaces")
    monkeypatch.setattr(ingestion, "_ws_root", lambda: tmp_path / "workspaces")

    client = _client()
    resp = client.post("/api/knowledge/upload", data={"workspace_id": "rag_ws"})

    assert resp.status_code == 400
    assert resp.get_json()["error"] == "no file provided"
```

- [ ] **Step 2: Run tests to verify RED**

Run: `./venv/bin/python -m pytest harness/test_rag_context_foundation.py::test_knowledge_upload_markdown_indexes_source harness/test_rag_context_foundation.py::test_knowledge_upload_requires_file -q`

Expected: fail because `/api/knowledge/upload` does not exist.

- [ ] **Step 3: Implement upload endpoint**

In `backend/api/knowledge_routes.py`, add `POST /api/knowledge/upload` inside `register_knowledge_routes(app)`.

Implementation details:

- Validate `workspace_id` with `_validated_ws_id`.
- Use `request.files["file"]`.
- Sanitize filename with `re.sub(r"[^a-zA-Z0-9_.-]", "_", filename)[:120]`.
- Save under `workspace.manager.WS_ROOT / ws_id / "uploads" / safe_filename`.
- Call `agent.modules.knowledge.service.import_file`.
- Return `{ok, source: {source_id, title, chunk_count, parent_count, source_type, scope, language, format, warnings}, summary}`.
- On `ok=False`, return status 400 with `errors` and `summary`.
- Never return the saved local path.

- [ ] **Step 4: Run upload tests to verify GREEN**

Run: `./venv/bin/python -m pytest harness/test_rag_context_foundation.py::test_knowledge_upload_markdown_indexes_source harness/test_rag_context_foundation.py::test_knowledge_upload_requires_file -q`

Expected: `2 passed`.

### Task 2: RAG Context Items And SafeLLMContext

**Files:**
- Modify: `context/loader.py`
- Modify: `context/builder.py`
- Modify: `context/schemas.py`
- Modify: `agent/runtime/context_builder.py`
- Modify: `agent/runtime/loop.py`
- Test: `harness/test_rag_context_foundation.py`

- [ ] **Step 1: Write failing context tests**

Append tests:

```python
def _seed_knowledge(tmp_path, monkeypatch):
    from artifacts import store as artifact_store
    from agent.modules.knowledge import ingestion
    from agent.modules.knowledge.service import import_file
    monkeypatch.setattr(artifact_store, "WS_ROOT", tmp_path / "workspaces")
    monkeypatch.setattr(ingestion, "_ws_root", lambda: tmp_path / "workspaces")
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
```

- [ ] **Step 2: Run tests to verify RED**

Run: `./venv/bin/python -m pytest harness/test_rag_context_foundation.py -q`

Expected: upload tests may pass after Task 1, context tests fail because `knowledge_hits` and `knowledge_chunk` are missing.

- [ ] **Step 3: Implement context retrieval**

In `context/schemas.py`, add `knowledge_hits: list = field(default_factory=list)` to `SafeLLMContext`.

In `context/loader.py`, after memory loading, call `agent.modules.knowledge.service.query_knowledge(query=user_input, workspace_id=workspace_id, top_k=5)` when `user_input` exists. Add each `source_summary` or `hits` entry as `ContextItem(item_type="knowledge_chunk", priority=15, content={safe fields only})`.

In `context/builder.py`, collect compressed `knowledge_chunk` items into `safe.knowledge_hits` and build `safe.citations` with `K1`, `K2`, etc.

In `agent/runtime/context_builder.py`, copy `knowledge_hits` and `citations` from bundle safe context into the flat `ctx.safe_context`.

In `agent/runtime/loop.py`, allow `_safe_context_prompt_text` to include `knowledge_hits`.

- [ ] **Step 4: Run context tests to verify GREEN**

Run: `./venv/bin/python -m pytest harness/test_rag_context_foundation.py -q`

Expected: all tests pass.

### Task 3: Frontend Upload Panel

**Files:**
- Modify: `frontend/src/api/index.ts`
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/pages/KnowledgeLibrary/KnowledgeLibrary.tsx`
- Test: `frontend/src/test/knowledgeUpload.test.tsx`

- [ ] **Step 1: Write failing frontend test**

Create `frontend/src/test/knowledgeUpload.test.tsx`:

```tsx
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { KnowledgeLibrary } from "../pages/KnowledgeLibrary/KnowledgeLibrary";
import { enqueue, resetApiMock } from "./setupApiMock";

describe("KnowledgeLibrary upload", () => {
  it("shows local upload controls", async () => {
    resetApiMock();
    enqueue("/workspaces", { status: 200, data: { workspaces: [{ workspace_id: "default", name: "default", is_default: true, created_at: "", stats: { session_count: 0, artifact_count: 0, knowledge_source_count: 0 } }] } });
    enqueue("/knowledge/sources", { status: 200, data: { ok: true, sources: [], counts: {} } });
    enqueue("/knowledge/search", { status: 200, data: { ok: true, query: "", results: [], count: 0 } });
    enqueue("/workspaces/default/artifacts", { status: 200, data: { artifacts: [] } });

    render(<KnowledgeLibrary />);

    expect(await screen.findByTestId("knowledge-upload-card")).toBeInTheDocument();
    expect(screen.getByTestId("knowledge-upload-file")).toBeInTheDocument();
    expect(screen.getByTestId("btn-knowledge-upload")).toBeDisabled();
  });

  it("uploads a selected file", async () => {
    resetApiMock();
    enqueue("/workspaces", { status: 200, data: { workspaces: [{ workspace_id: "default", name: "default", is_default: true, created_at: "", stats: { session_count: 0, artifact_count: 0, knowledge_source_count: 0 } }] } });
    enqueue("/knowledge/sources", { status: 200, data: { ok: true, sources: [], counts: {} } });
    enqueue("/knowledge/search", { status: 200, data: { ok: true, query: "", results: [], count: 0 } });
    enqueue("/workspaces/default/artifacts", { status: 200, data: { artifacts: [] } });
    enqueue("/knowledge/upload", { status: 200, data: { ok: true, source: { source_id: "ksrc_1", workspace_id: "default", title: "OSPF", tags: [], enabled: true, chunk_count: 1, created_at: "" } } });
    enqueue("/knowledge/sources", { status: 200, data: { ok: true, sources: [{ source_id: "ksrc_1", workspace_id: "default", title: "OSPF", tags: [], enabled: true, chunk_count: 1, created_at: "", status: "indexed" }], counts: {} } });

    render(<KnowledgeLibrary />);
    const file = new File(["# OSPF"], "ospf.md", { type: "text/markdown" });
    await userEvent.upload(await screen.findByTestId("knowledge-upload-file"), file);
    await userEvent.click(screen.getByTestId("btn-knowledge-upload"));

    expect(await screen.findByText(/OSPF/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run frontend test to verify RED**

Run: `npm test -- --run frontend/src/test/knowledgeUpload.test.tsx`

Expected: fail because upload controls/API are missing.

- [ ] **Step 3: Implement frontend upload**

Add `knowledgeApi.upload(workspace_id, file, opts)` using `FormData`.

In `KnowledgeLibrary.tsx`, add:

- file state
- title state
- tags state
- upload card with `data-testid="knowledge-upload-card"`
- file input `data-testid="knowledge-upload-file"`
- button `data-testid="btn-knowledge-upload"`
- success toast and `sources.reload()`

- [ ] **Step 4: Run frontend test to verify GREEN**

Run: `npm test -- --run frontend/src/test/knowledgeUpload.test.tsx`

Expected: tests pass.

### Task 4: Integration Verification And Commit

**Files:**
- All modified files

- [ ] **Step 1: Run backend targeted tests**

Run: `./venv/bin/python -m pytest harness/test_rag_context_foundation.py harness/test_context_prompt_harness.py harness/test_runtime_hardening_v063.py -q`

Expected: pass.

- [ ] **Step 2: Run frontend targeted tests**

Run: `npm test -- --run frontend/src/test/knowledgeUpload.test.tsx frontend/src/test/apiError.test.tsx frontend/src/test/sourceSummary.test.tsx`

Expected: pass.

- [ ] **Step 3: Run compile/type checks**

Run: `./venv/bin/python -m compileall backend agent context workspace -q`

Run: `npm run typecheck`

Expected: both pass.

- [ ] **Step 4: Commit and push**

Run:

```bash
git add backend/api/knowledge_routes.py context/loader.py context/builder.py context/schemas.py agent/runtime/context_builder.py agent/runtime/loop.py frontend/src/api/index.ts frontend/src/types/index.ts frontend/src/pages/KnowledgeLibrary/KnowledgeLibrary.tsx frontend/src/test/knowledgeUpload.test.tsx harness/test_rag_context_foundation.py docs/superpowers/plans/2026-06-12-rag-context-foundation.md
git commit -m "feat: add rag knowledge upload and context retrieval"
git push
```

Expected: changes pushed to `main`.

## Self-Review

- Spec coverage: upload API, UI upload, RAG context retrieval, safe prompt injection, and tests are covered.
- Scope: this plan implements the file-based RAG foundation only. Embeddings, reranking, OCR, and vector databases remain out of scope.
- Type consistency: backend uses `knowledge_hits`, frontend uses existing `KnowledgeSource` with optional response fields, and citations use `citation_id/source_id/chunk_id/title`.
