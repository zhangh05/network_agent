# Knowledge Search Skill

## Status

- Public capability projection: `knowledge.search`
- Runtime knowledge capability: enabled
- Skill registry entry: currently marked planned in `skills/registry.yaml`

## Current Implementation

Knowledge search is available through:

- API: `GET /api/knowledge/search`
- Upload API: `POST /api/knowledge/upload`
- Unified retrieval: `context/retrieval.py`
- Module service: `agent/modules/knowledge/service.py`
- Safe store/search: `knowledge/`

## Behavior

- Searches safe excerpts only.
- Does not return full sensitive source content.
- Can be combined with memory evidence in runtime RAG context.
- Emits citation-ready source cards through unified retrieval.

## Red Lines

- No LLM calls from inside the search skill.
- No absolute local paths in user-visible output.
- No secrets, keys, or raw sensitive config in context.
