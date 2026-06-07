# knowledge_search — 知识库搜索

## Status
enabled ✓

## Description
Search the network engineering knowledge base for relevant cases and templates. Uses Safe RAG to filter sensitive content before injecting into LLM context.

## Entrypoint
- **Adapter**: `skills/knowledge_search/adapter.py::search()`
- **Agent routing**: `agent/nodes/composer.py::_compose_knowledge_query()`
- **Safe RAG**: `context/knowledge_loader.py::load_knowledge_context()`

## API
- `/api/knowledge/search` — Search indexed knowledge artifacts

## Red Lines
- No LLM calls from within skill
- No absolute paths in output
- No secret/sensitive content in context
