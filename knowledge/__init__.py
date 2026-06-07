# knowledge/__init__.py
"""Knowledge Index Runtime — Safe Local RAG Foundation.

Module structure:
  schemas.py  — KnowledgeSource, SafeChunk, SearchResult
  store.py    — Local index store (JSONL-based)
  chunker.py  — Safe text chunking with redaction
  policy.py   — Security gates (sensitivity, lifecycle, forbidden patterns)
  search.py   — Keyword + metadata search
"""
