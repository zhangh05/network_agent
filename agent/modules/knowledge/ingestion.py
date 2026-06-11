# agent/modules/knowledge/ingestion.py
"""Document ingestion (v1.0.1).

Pipeline:
  raw file (md/txt/html/docx/pdf)
    -> parse_document()  (parsers/)
    -> NormalizedDocument
    -> chunk_document()  (chunking.py)
    -> (parents, children)
    -> save to v1.0 KnowledgeStore (as a single source record
       containing the full normalized_markdown, plus metadata
       describing chunk counts) AND
       save parents + children to the chunk store (index.py)

We deliberately keep the v1.0 source store as the single source of
truth for *what* is in the library (title, author, edition, scope,
format, language) and the v1.0.1 chunk store as the source of truth
for *how* it is chunked. The two are cross-referenced via source_id.

Strict contract:
  - Never fabricate author / edition / page numbers / chapter
    numbers. The parsers only surface what the format itself
    declares.
  - Scanned PDFs return ok=False with error="unsupported_ocr".
  - The full normalized_markdown is stored verbatim in the source
    record; children do NOT mix in any "retrieval prefix".
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Union

from agent.modules.knowledge import parsers as _parsers
from agent.modules.knowledge import chunking as _chunking
from agent.modules.knowledge import index as _index
from agent.modules.knowledge import store as _store
from agent.modules.knowledge.schemas import (
    KnowledgeChunk, NormalizedDocument, SOURCE_TYPES, SCOPES,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def import_file(
    workspace_id: str,
    source: Union[str, bytes, "Path"],
    *,
    title: str = "",
    author: str = "",
    edition: str = "",
    source_type: str = "project_doc",
    scope: str = "workspace",
    language: str = "zh",
    tags: Optional[List[str]] = None,
    metadata: Optional[dict] = None,
) -> dict:
    """Top-level ingestion: file -> source + chunks.

    Returns:
      {
        ok, summary, source_id,
        source_type, format, scope, language,
        chunk_count, parent_count,
        warnings, errors,
      }
    """
    if not workspace_id:
        return {"ok": False, "summary": "workspace_id is required",
                "errors": ["missing_workspace_id"]}
    if source_type not in SOURCE_TYPES:
        return {"ok": False,
                "summary": f"invalid source_type: {source_type}",
                "errors": ["invalid_source_type"]}
    if scope not in SCOPES:
        return {"ok": False,
                "summary": f"invalid scope: {scope}",
                "errors": ["invalid_scope"]}

    # 1. Parse
    try:
        doc = _parsers.parse_document(
            source,
            title=title, author=author, source_type=source_type,
            scope=scope, language=language, metadata=metadata,
        )
    except _parsers.UnsupportedFormatError as e:
        return {"ok": False, "summary": f"unsupported format: {e}",
                "errors": ["unsupported_format"]}
    except Exception as e:
        return {"ok": False, "summary": f"parser error: {e!r}",
                "errors": ["parser_failed"]}

    # 2. Scanned PDF? -> return ok=False
    if "unsupported_ocr" in (doc.warnings or []):
        return {
            "ok": False,
            "summary": ("扫描型 PDF 不支持 OCR 解析。请提供文本型 PDF "
                        "或转换为可解析的格式后重试。"),
            "format": doc.format,
            "errors": ["unsupported_ocr"],
            "warnings": doc.warnings,
        }

    if not doc.normalized_markdown.strip():
        return {
            "ok": False,
            "summary": f"document produced empty normalized_markdown",
            "format": doc.format,
            "errors": ["empty_document"],
            "warnings": doc.warnings,
        }

    # 3. Save to v1.0 source store
    full_title = (title or doc.title or "").strip()[:500] or "untitled"
    source_meta = dict(doc.metadata or {})
    source_meta.update({
        "source_type": source_type,
        "scope": scope,
        "language": language,
        "format": doc.format,
        "author": author or doc.author,
        "edition": edition,
        "tags": list(tags or []),
        "normalized_title": doc.title,
        "warnings": list(doc.warnings or []),
    })
    saved = _store.import_document(
        workspace_id=workspace_id,
        title=full_title,
        content=doc.normalized_markdown,
        source=f"{source_type}/{doc.format}",
        metadata=source_meta,
    )
    if not saved.get("ok"):
        return {
            "ok": False,
            "summary": saved.get("summary", "import_document failed"),
            "errors": saved.get("errors", ["store_failed"]),
        }
    source_id = saved["source"]["source_id"]

    # 4. Chunk
    doc.source_id = source_id
    parents, children = _chunking.chunk_document(doc)

    # 5. Inject source-level metadata into each chunk's metadata.
    base_meta = {
        "scope": scope,
        "source_type": source_type,
        "source_title": full_title,
        "author": author or doc.author,
        "edition": edition,
        "language": language,
        "format": doc.format,
        "tags": list(tags or []),
    }
    for c in parents:
        c.metadata.update(base_meta)
    for c in children:
        c.metadata.update(base_meta)
    # Re-build index_text for children with source_title (so BM25
    # scores against the title boost).
    for c in children:
        c.index_text = (
            f"{full_title} | {c.chapter} | {c.section} | "
            f"{' '.join(tags or [])} | {c.content}"
        )
    for c in parents:
        c.index_text = (
            f"{full_title} | {c.chapter} | {c.section} | "
            f"{' '.join(tags or [])} | {c.content}"
        )

    # 6. Save chunks (replace any prior for this source_id)
    n = _index.replace_chunks(workspace_id, source_id, parents + children)

    return {
        "ok": True,
        "summary": (
            f"Imported {full_title} ({doc.format}) as {source_id} "
            f"with {len(parents)} parent + {len(children)} child chunks."
        ),
        "source_id": source_id,
        "title": full_title,
        "source_type": source_type,
        "format": doc.format,
        "scope": scope,
        "language": language,
        "parent_count": len(parents),
        "chunk_count": len(children),
        "warnings": list(doc.warnings or []),
        "errors": [],
    }


def reindex_source(workspace_id: str, source_id: str) -> dict:
    """Re-parse the source's normalized_markdown and rebuild chunks.

    Used after the source is updated in the v1.0 store, or when the
    chunker parameters have changed.
    """
    if not workspace_id or not source_id:
        return {"ok": False, "summary": "workspace_id and source_id are required",
                "errors": ["missing_inputs"]}
    rec = _store.read_source(workspace_id, source_id)
    if rec is None:
        return {"ok": False,
                "summary": f"source not found: {source_id}",
                "errors": ["source_not_found"]}
    src = rec
    full_markdown = rec.get("content", "") or ""
    meta = src.get("metadata", {}) or {}
    doc = NormalizedDocument(
        source_id=source_id,
        title=src.get("title", ""),
        author=meta.get("author", ""),
        edition=meta.get("edition", ""),
        source_type=meta.get("source_type", "project_doc"),
        scope=meta.get("scope", "workspace"),
        language=meta.get("language", "zh"),
        format=meta.get("format", "md"),
        normalized_markdown=full_markdown,
        metadata=meta,
        warnings=list(meta.get("warnings") or []),
    )
    parents, children = _chunking.chunk_document(doc)
    base_meta = {
        "scope": doc.scope,
        "source_type": doc.source_type,
        "source_title": doc.title,
        "author": doc.author,
        "edition": doc.edition,
        "language": doc.language,
        "format": doc.format,
        "tags": list(meta.get("tags") or []),
    }
    for c in parents:
        c.metadata.update(base_meta)
    for c in children:
        c.metadata.update(base_meta)
    n = _index.replace_chunks(workspace_id, source_id, parents + children)
    return {
        "ok": True,
        "summary": f"Reindexed {source_id}: {len(parents)} parents, {len(children)} children",
        "source_id": source_id,
        "parent_count": len(parents),
        "chunk_count": len(children),
        "errors": [], "warnings": [],
    }
