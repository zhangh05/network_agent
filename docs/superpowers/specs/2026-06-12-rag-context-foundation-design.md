# RAG Context Foundation Design

Date: 2026-06-12

## Goal

Make the knowledge library, context system, memory system, and file/artifact system work as one information foundation for the agent.

The current codebase already has document parsing, chunking, indexing, artifact storage, and memory retrieval, but they are not wired into the main `/api/agent/message` RuntimeLoop as a first-class RAG context. The product should let a user upload local documents, search them, and have the agent automatically use safe retrieved excerpts during normal chat.

## Current Gaps

- Knowledge ingestion exists in `agent.modules.knowledge.ingestion.import_file`, but the frontend only exposes "import from artifact".
- `backend.api.knowledge_routes` has source and search APIs, but no direct multipart upload endpoint for local files.
- `context.loader.load_context_items` loads request, workspace, memory, artifacts, jobs, and reports, but not `knowledge_chunk` items.
- `SafeLLMContext` has memory and artifact fields but no explicit `knowledge_hits`.
- RuntimeLoop now injects safe context into messages, but knowledge chunks are not present in that safe context.
- Memory, knowledge, and artifacts have overlapping purposes in the UI. Users cannot easily tell what should be uploaded, remembered, indexed, or treated as an output artifact.

## Product Model

Use three distinct information types:

- Knowledge: user-provided documents and indexed reference material. Examples: design docs, vendor guides, troubleshooting notes, PDFs, DOCX, Markdown, runbooks. Knowledge is retrieved by query and cited as evidence.
- Memory: durable user/workspace facts and preferences. Examples: default vendor, naming conventions, project assumptions, recurring constraints. Memory should not store full documents.
- Artifacts: files and outputs produced or uploaded in a workspace. Examples: translated configs, reports, generated summaries, uploaded raw files, review outputs. Artifacts can be promoted into knowledge when useful.

The UI can describe this without exposing raw implementation terms:

- "上传文档到知识库" for Knowledge.
- "记住这个偏好/事实" for Memory.
- "保存/查看产物" for Artifacts.

## Recommended Approach

Implement a workspace-scoped RAG foundation using the existing file-based stores:

1. Add direct knowledge upload.
2. Index uploaded files through the existing parser/chunker/index pipeline.
3. Add knowledge retrieval to the context builder.
4. Inject safe knowledge excerpts and citations into RuntimeLoop messages.
5. Surface knowledge references in the UI.
6. Add harness and frontend tests around the main `/api/agent/message` path.

No vector database is required for this phase. The current BM25-like chunk search can be hardened first; embeddings and reranking can come later behind the same interfaces.

## Backend Design

### Upload Endpoint

Add `POST /api/knowledge/upload`.

Request:

- Multipart form field `file`
- `workspace_id`
- Optional `title`
- Optional `source_type`, default `project_doc`
- Optional `scope`, default `workspace`
- Optional `language`, default `zh`
- Optional comma-separated `tags`

Flow:

1. Validate `workspace_id`.
2. Validate file presence, filename, and size.
3. Save the upload under `workspaces/<workspace_id>/uploads/<safe_filename>`.
4. Call `agent.modules.knowledge.service.import_file(...)`.
5. Return source metadata, chunk counts, warnings, and errors.
6. Keep the uploaded file as an upload record only if needed; the indexed source and chunks are the source of truth for retrieval.

Security:

- Reuse `import_file` allowlist validation so only `uploads/` and `inbox/` can be indexed.
- Preserve existing PDF/DOCX/archive limits.
- Never return absolute paths.
- Return parser errors as user-readable messages.

### Context Loading

Extend `context.loader.load_context_items` with knowledge retrieval.

Rules:

- Run retrieval when `user_input` is non-empty.
- Use `agent.modules.knowledge.service.query_knowledge` or `search_chunks`.
- Add each safe result as `ContextItem(item_type="knowledge_chunk")`.
- Store only safe fields: `chunk_id`, `source_id`, `title`, `safe_excerpt`, `summary`, `score`, `tags`, `source_type`, `citation_id`.
- Do not include full normalized Markdown, raw file content, local paths, or secret-bearing fields.
- Give knowledge chunks higher priority than generic artifacts and memory for explicit knowledge questions.

### SafeLLMContext

Add:

- `knowledge_hits: list`
- `citations: list`

`context.builder.build_context_bundle` should collect compressed `knowledge_chunk` items into `SafeLLMContext.knowledge_hits` and produce compact citations such as:

```json
{
  "citation_id": "K1",
  "source_id": "ksrc_xxx",
  "chunk_id": "kchk_xxx",
  "title": "OSPF Runbook"
}
```

### RuntimeLoop Prompt Context

Extend `_safe_context_prompt_text` to include:

- `knowledge_hits`
- `citations`

The injected prompt block should tell the model:

- Use knowledge hits as supporting evidence.
- Cite titles or citation ids when answering.
- If retrieval is empty or insufficient, say what is missing.
- Do not invent sources.

### Memory Boundary

Keep memory retrieval in `context.loader`, but treat it separately from knowledge:

- Memory should be short and durable.
- Memory hits can influence style, defaults, and project assumptions.
- Knowledge hits answer document-backed factual questions.

Do not store uploaded documents as memory records.

## Frontend Design

### Knowledge Library

Add an upload panel above the source list:

- File input for `.md`, `.txt`, `.html`, `.docx`, `.pdf`
- Title field, optional
- Scope selector: workspace/session/global if backend supports it; otherwise show workspace only
- Tags input, optional
- Upload button
- Inline result: source title, chunk count, warnings, failure reason

Keep "从 artifact 导入" as a secondary path.

Source list should remain user-facing:

- 文档名
- 内容类型
- 是否可检索
- 最后更新
- 操作: 重新整理

Raw ids and chunk details stay under "技术详情".

### Agent Workbench

When a turn uses knowledge:

- Show a compact "参考知识源" section in the inspector.
- Show source title, safe excerpt, and citation id.
- Do not show full chunks by default.

## Testing Design

### Backend Harness

Add tests for:

- `POST /api/knowledge/upload` accepts a small Markdown file and returns `source_id` plus `chunk_count`.
- Upload rejects oversized files and missing files.
- Upload response contains no absolute path.
- `context.loader` produces `knowledge_chunk` items for a query that matches an indexed document.
- `build_context_bundle` places hits into `SafeLLMContext.knowledge_hits`.
- `_build_initial_messages` includes safe knowledge excerpts and citations.
- Main `/api/agent/message` path can see knowledge context in LLM messages when `invoke_llm` is patched.

### Frontend Tests

Add or update tests for:

- Knowledge page shows upload controls.
- Successful upload refreshes source list.
- Upload failure shows readable error.
- Search still works after upload.

### Safety Tests

Ensure:

- No `source_config`, `deployable_config`, `password`, `token`, or absolute path appears in knowledge search results, safe context, or injected LLM messages.
- Sensitive uploaded content is either redacted or excluded from safe excerpts.

## Rollout Plan

Phase 1:

- Backend upload endpoint.
- Frontend upload panel.
- Basic upload/search tests.

Phase 2:

- Knowledge retrieval inside `context.loader`.
- `SafeLLMContext.knowledge_hits`.
- RuntimeLoop prompt injection.
- Main `/api/agent/message` harness coverage.

Phase 3:

- UI references in workbench inspector.
- Better source status and error display.
- Optional context diagnostics showing what was retrieved and why.

## Non-Goals For This Phase

- No external vector database.
- No embedding model dependency.
- No OCR for scanned PDFs.
- No full file content injection into LLM prompts.
- No automatic conversion of every artifact into knowledge.

## Open Implementation Notes

- Prefer existing `agent.modules.knowledge.service.import_file` over creating a parallel importer.
- Keep storage workspace-scoped and file-based.
- Keep all user-visible errors in Chinese.
- Keep raw diagnostic fields in collapsible technical details, not first-level UI.
