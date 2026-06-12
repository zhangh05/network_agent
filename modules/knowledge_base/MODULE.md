# Knowledge Base Module

## Status

- Product module registry status: `enabled`
- Runtime knowledge capability: enabled through the runtime capability registry
- Frontend page: `/knowledge`

## Current Behavior

The active knowledge implementation is provided by:

- `backend/api/knowledge_routes.py`
- `knowledge/`
- `agent/modules/knowledge/`
- `context/retrieval.py`
- `memory/indexer.py`

The UI supports local upload, artifact import, source list, reindex, and search. Runtime RAG can use both knowledge and memory evidence.

## Boundary

The module registry and runtime knowledge capability are both active. Planned work should extend the current RAG-backed implementation rather than creating a separate knowledge surface.
