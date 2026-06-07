# knowledge/store.py
"""Knowledge Index Store — local JSONL-based persistence.

Index files live under:
  workspaces/<ws_id>/indexes/knowledge/

Structure:
  sources.jsonl     — KnowledgeSource records
  chunks.jsonl      — SafeChunk records
"""

import json
import os
import time
from pathlib import Path
from typing import Optional, List

from workspace.ids import validate_workspace_id
from knowledge.schemas import KnowledgeSource, SafeChunk


ROOT = Path(__file__).resolve().parent.parent
WS_ROOT = ROOT / "workspaces"


def _index_dir(workspace_id: str) -> Path:
    validate_workspace_id(workspace_id)
    return WS_ROOT / workspace_id / "indexes" / "knowledge"


def _sources_path(workspace_id: str) -> Path:
    return _index_dir(workspace_id) / "sources.jsonl"


def _chunks_path(workspace_id: str) -> Path:
    return _index_dir(workspace_id) / "chunks.jsonl"


def _ensure_dirs(workspace_id: str):
    _index_dir(workspace_id).mkdir(parents=True, exist_ok=True)


# ═══════════════ Source CRUD ═══════════════

def save_source(source: KnowledgeSource) -> KnowledgeSource:
    """Save or update a knowledge source."""
    _ensure_dirs(source.workspace_id)
    source.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    spath = _sources_path(source.workspace_id)

    # Read existing sources
    existing = _read_jsonl(spath)
    found = False
    updated = []
    for rec in existing:
        if rec.get("source_id") == source.source_id:
            updated.append(source.as_dict())
            found = True
        else:
            updated.append(rec)
    if not found:
        updated.append(source.as_dict())

    _write_jsonl(spath, updated, key="source_id")
    return source


def get_source(workspace_id: str, source_id: str) -> Optional[dict]:
    """Get a knowledge source by ID."""
    validate_workspace_id(workspace_id)
    spath = _sources_path(workspace_id)
    for rec in _read_jsonl(spath):
        if rec.get("source_id") == source_id:
            return rec
    return None


def get_source_by_artifact(workspace_id: str, artifact_id: str) -> Optional[dict]:
    """Get a knowledge source by artifact ID."""
    validate_workspace_id(workspace_id)
    spath = _sources_path(workspace_id)
    for rec in _read_jsonl(spath):
        if rec.get("artifact_id") == artifact_id:
            return rec
    return None


def list_sources(workspace_id: str, status: str = None) -> List[dict]:
    """List knowledge sources, optionally filtered by status."""
    validate_workspace_id(workspace_id)
    spath = _sources_path(workspace_id)
    results = _read_jsonl(spath)
    if status:
        results = [r for r in results if r.get("status") == status]
    return results


def delete_source(workspace_id: str, source_id: str) -> bool:
    """Delete a knowledge source and its chunks."""
    validate_workspace_id(workspace_id)
    spath = _sources_path(workspace_id)
    cpath = _chunks_path(workspace_id)

    sources = [r for r in _read_jsonl(spath) if r.get("source_id") != source_id]
    if len(sources) == len(_read_jsonl(spath)):
        return False  # Not found

    _write_jsonl(spath, sources, key="source_id")

    # Also remove chunks
    chunks = [c for c in _read_jsonl(cpath) if c.get("source_id") != source_id]
    _write_jsonl(cpath, chunks, key="chunk_id")
    return True


def get_source_count(workspace_id: str) -> dict:
    """Get source counts by status."""
    validate_workspace_id(workspace_id)
    spath = _sources_path(workspace_id)
    counts = {"total": 0, "pending": 0, "indexing": 0, "indexed": 0, "failed": 0}
    for rec in _read_jsonl(spath):
        counts["total"] += 1
        status = rec.get("status", "pending")
        if status in counts:
            counts[status] += 1
    return counts


# ═══════════════ Chunk CRUD ═══════════════

def save_chunks(chunks: List[SafeChunk]):
    """Save chunks to the index store."""
    if not chunks:
        return
    ws_id = chunks[0].workspace_id
    _ensure_dirs(ws_id)
    cpath = _chunks_path(ws_id)

    existing = _read_jsonl(cpath)
    # Remove old chunks for these sources
    source_ids = list(set(c.source_id for c in chunks))
    existing = [c for c in existing if c.get("source_id") not in source_ids]

    for chunk in chunks:
        existing.append(chunk.as_dict())

    _write_jsonl(cpath, existing, key="chunk_id")


def get_chunk(workspace_id: str, chunk_id: str) -> Optional[dict]:
    """Get a single chunk by ID."""
    validate_workspace_id(workspace_id)
    cpath = _chunks_path(workspace_id)
    for rec in _read_jsonl(cpath):
        if rec.get("chunk_id") == chunk_id:
            return rec
    return None


def list_chunks(workspace_id: str, source_id: str = None,
                llm_safe_only: bool = True) -> List[dict]:
    """List chunks, optionally filtered."""
    validate_workspace_id(workspace_id)
    cpath = _chunks_path(workspace_id)
    results = _read_jsonl(cpath)
    if source_id:
        results = [c for c in results if c.get("source_id") == source_id]
    if llm_safe_only:
        results = [c for c in results if c.get("llm_safe", True)]
    return results


# ═══════════════ JSONL Helpers ═══════════════

def _read_jsonl(path: Path) -> list:
    """Read JSONL file, returning list of dicts."""
    if not path.exists():
        return []
    results = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    results.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return results


def _write_jsonl(path: Path, records: list, key: str = "source_id"):
    """Write records to JSONL, deduplicated by key."""
    path.parent.mkdir(parents=True, exist_ok=True)
    seen = set()
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            k = rec.get(key, "")
            if k not in seen:
                seen.add(k)
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
