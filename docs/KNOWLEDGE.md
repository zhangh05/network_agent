# Knowledge

Knowledge functionality is implemented in two places:

- Runtime capability module: `agent/modules/knowledge/`
- API routes: `backend/api/knowledge_routes.py`

## Runtime Module

Important files:

- `agent/modules/knowledge/service.py`
- `agent/modules/knowledge/store.py`
- `agent/modules/knowledge/ingestion.py`
- `agent/modules/knowledge/chunking.py`
- `agent/modules/knowledge/index.py`
- `agent/modules/knowledge/tools.py`
- `agent/modules/knowledge/parsers/`

## Ingestion

Supported parser modules include Markdown, text, HTML, DOCX, and text PDF. Scanned PDFs return an unsupported OCR status rather than fabricating content.

`knowledge.import_file` is restricted to workspace-controlled upload and inbox areas. Path traversal, symlink escape, missing files, oversized files, and DOCX archive bombs are rejected.

## Retrieval

The current retrieval path is lexical BM25 with:

- mixed word and CJK n-gram tokenization
- field weighting
- deterministic query expansions
- scope boost
- parent expansion
- sibling chunk deduplication
- no fabricated hits

Current scoring metadata includes tokenizer/scoring version, query expansions, lexical score, final score, and filtering counts.

## API

- `GET /api/knowledge/sources`
- `POST /api/knowledge/sources/from-artifact`
- `POST /api/knowledge/sources/<source_id>/reindex`
- `GET /api/knowledge/search`
- `GET /api/knowledge/chunks/<chunk_id>`
