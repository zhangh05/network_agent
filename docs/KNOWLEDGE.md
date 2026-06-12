# Knowledge And Memory

Current knowledge and memory behavior is RAG-backed.

## Knowledge Surfaces

| Area | Current source |
|---|---|
| API routes | `backend/api/knowledge_routes.py` |
| Artifact-backed index | `knowledge/` |
| Module ingestion/search service | `agent/modules/knowledge/` |
| Unified RAG retrieval | `context/retrieval.py` |
| Frontend page | `frontend/src/pages/KnowledgeLibrary/KnowledgeLibrary.tsx` |

## Upload And Ingestion

`POST /api/knowledge/upload` accepts local files from the frontend Knowledge Library:

- Markdown
- text
- HTML
- DOCX
- PDF text

Uploaded files are saved to the workspace upload area, imported, and then removed from the temporary upload path. The UI lets users set title, tags, and scope.

## Artifact Import

`POST /api/knowledge/sources/from-artifact` indexes safe artifact excerpts. It does not expose full sensitive artifact content to search results.

## Search API

`GET /api/knowledge/search` returns safe excerpts only. Results merge the current `knowledge/` index with module-backed knowledge hits and return:

- `chunk_id`
- `source_id`
- `artifact_id`
- `title`
- `summary`
- `safe_excerpt`
- sensitivity/type metadata
- score metadata

## Unified RAG Retrieval

`context/retrieval.py` is the turn-context retrieval layer. It:

- queries document source buckets separately from memory
- queries memory through its RAG projection
- creates query variants
- deduplicates chunks
- applies local token-similarity semantic reranking
- emits source cards with citation ids such as `[K1]` for knowledge and `[M1]` for memory
- returns diagnostics with retriever and rerank metadata

## Memory System

Memory code lives in `memory/`.

Current behavior:

- memory writes are redacted before persistence
- policy blocks unsafe or low-confidence writes
- user-confirmed decisions and preferences can become long-term memory
- memory records are projected into RAG best-effort through `memory/indexer.py`
- deleting memory deletes its projection
- `memory/conflicts.py` detects likely contradictions for the same project/type
- API responses from memory write/confirm include conflict metadata when detected

## Context Use

The runtime context builder can include both knowledge and memory evidence. The prompt requires factual claims based on retrieved context to cite source ids when citations exist.

## Frontend

The Knowledge Library page supports:

- suggested searches
- local file upload
- artifact import
- source list and reindex
- keyword search over safe excerpts
- technical details under collapsible sections
