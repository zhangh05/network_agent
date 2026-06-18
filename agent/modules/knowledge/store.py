# agent/modules/knowledge/store.py
"""Knowledge Store (v1.0).

A workspace-scoped, file-based local knowledge store. Each workspace
has its own directory:

    {ws_root}/{workspace_id}/sys/knowledge/
        sources.jsonl        # one Source per line
        index.json           # metadata: version, source_count, last_query_at

Storage format: JSONL (one JSON object per line). No external database
dependency. Each Source is:

    {
        "source_id":  str,                # stable, generated at import
        "title":      str,
        "content":    str,
        "source":     str,                # user-supplied origin label
        "enabled":    bool,               # soft-disable flag
        "deleted":    bool,               # hard-delete / soft-delete marker
        "created_at": str (iso8601),
        "updated_at": str (iso8601),
        "metadata":   dict
    }

Public API:
    import_document(workspace_id, title, content, source, metadata)
    list_sources(workspace_id, include_disabled=False, include_deleted=False)
    read_source(workspace_id, source_id)
    disable_source(workspace_id, source_id, disabled=True)
    delete_source(workspace_id, source_id)        # soft delete
    query(workspace_id, query, top_k, filters)    # enabled sources only

Strict contract:
    - NEVER fabricates sources, scores, or citations.
    - NEVER returns local absolute paths to the caller.
    - NEVER touches real devices.
    - Storage failure surfaces ok=False with errors=[…].
"""

from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


KNOWLEDGE_DIR_NAME = "sys/knowledge"
SOURCES_FILE = "sources.jsonl"
INDEX_FILE = "index.json"
STORE_VERSION = "1.0"

# Source ID prefix so it's easy to identify in logs.
SOURCE_ID_PREFIX = "ksrc_"

# Max content length for a single source (defensive cap).
MAX_CONTENT_LEN = 200_000

# Max title length.
MAX_TITLE_LEN = 500

# Local-path-like substring pattern — we never let this leak in the
# caller-visible `source` field by accident.
_LOCAL_PATH_PATTERN = re.compile(r"(/Users/|/home/|/var/|/tmp/|C:\\|\\\\)")


# v1.0 in-process lock to make read-modify-write atomic. The store is
# process-local; per-workspace lock is sufficient.
_store_locks: dict[str, threading.RLock] = {}
_store_locks_guard = threading.Lock()


def _get_lock(workspace_id: str) -> threading.RLock:
    with _store_locks_guard:
        lock = _store_locks.get(workspace_id)
        if lock is None:
            lock = threading.RLock()
            _store_locks[workspace_id] = lock
        return lock


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ws_root() -> Path:
    """Workspace root. Mirrors agent/modules/review/service._ws_root()."""
    try:
        import workspace.manager as wm
        return wm.WS_ROOT
    except Exception:
        from artifacts.store import _get_ws_root
        return _get_ws_root()


def _store_dir(workspace_id: str) -> Path:
    return _ws_root() / workspace_id / KNOWLEDGE_DIR_NAME


def _sources_path(workspace_id: str) -> Path:
    return _store_dir(workspace_id) / SOURCES_FILE


def _index_path(workspace_id: str) -> Path:
    return _store_dir(workspace_id) / INDEX_FILE


def _ensure_store_dir(workspace_id: str) -> Path:
    d = _store_dir(workspace_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ensure_index(workspace_id: str) -> dict:
    """Read or initialize the index file."""
    p = _index_path(workspace_id)
    if p.exists():
        try:
            with open(p, "r", encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                return d
        except Exception:
            pass
    return {"version": STORE_VERSION, "workspace_id": workspace_id,
            "source_count": 0, "last_query_at": "",
            "created_at": _now_iso()}


def _save_index(workspace_id: str, idx: dict) -> None:
    p = _index_path(workspace_id)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=2)


def _generate_source_id() -> str:
    return f"{SOURCE_ID_PREFIX}{uuid.uuid4().hex[:16]}"


def _sanitize_source_label(source: str) -> str:
    """Defensive: strip absolute local paths from caller-visible labels.

    We never persist the raw `source` argument verbatim; if it looks
    like a local path, we replace it with a generic label. This keeps
    internal storage paths from leaking through the public API.
    """
    s = str(source or "").strip()
    if not s:
        return "unspecified"
    if _LOCAL_PATH_PATTERN.search(s):
        # Don't expose local paths in caller-visible records.
        return "redacted-local-path"
    return s[:200]


def _normalize_content(content: str) -> str:
    """Cap content length; keep newlines. Warns when truncation occurs."""
    if not isinstance(content, str):
        content = str(content or "")
    original_len = len(content)
    if original_len > MAX_CONTENT_LEN:
        import logging
        logging.getLogger("knowledge.v2").warning(
            "Content truncated from %d to %d chars (MAX_CONTENT_LEN=%d)",
            original_len, MAX_CONTENT_LEN, MAX_CONTENT_LEN,
        )
        content = content[:MAX_CONTENT_LEN]
    return content


def _read_sources_raw(workspace_id: str) -> list:
    """Read all source records verbatim from the JSONL file.

    Returns [] if the file doesn't exist or is empty.
    """
    p = _sources_path(workspace_id)
    if not p.exists():
        return []
    out = []
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                if isinstance(d, dict):
                    out.append(d)
            except Exception:
                # Skip malformed lines defensively.
                continue
    return out


def _write_sources_raw(workspace_id: str, sources: list) -> None:
    """Atomically replace the JSONL file with the given list."""
    _ensure_store_dir(workspace_id)
    p = _sources_path(workspace_id)
    tmp = p.with_suffix(".jsonl.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for s in sources:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
    tmp.replace(p)


def _public_view(rec: dict, include_content: bool = False) -> dict:
    """Build a caller-safe view of a source record.

    Never returns the raw storage path. Includes content only when
    asked.
    """
    out = {
        "source_id": rec.get("source_id", ""),
        "title": rec.get("title", ""),
        "source": rec.get("source", "unspecified"),
        "enabled": bool(rec.get("enabled", True)),
        "deleted": bool(rec.get("deleted", False)),
        "created_at": rec.get("created_at", ""),
        "updated_at": rec.get("updated_at", ""),
        "metadata": dict(rec.get("metadata") or {}),
    }
    if include_content:
        out["content"] = rec.get("content", "")
    return out


# ── Public API ──

def import_document(
    workspace_id: str,
    title: str,
    content: str,
    source: str = "",
    metadata: Optional[dict] = None,
) -> dict:
    """Import one document into the workspace knowledge store.

    Returns ok=True with the public view of the new source, or
    ok=False with errors=[…].
    """
    if not workspace_id:
        return {"ok": False, "summary": "workspace_id is required",
                "errors": ["missing_workspace_id"]}
    title = str(title or "").strip()[:MAX_TITLE_LEN]
    content = _normalize_content(content)
    if not title and not content:
        return {"ok": False,
                "summary": "title or content is required",
                "errors": ["missing_inputs"]}
    rec = {
        "source_id": _generate_source_id(),
        "title": title or "untitled",
        "content": content,
        "source": _sanitize_source_label(source),
        "enabled": True,
        "deleted": False,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "metadata": dict(metadata or {}),
    }
    with _get_lock(workspace_id):
        _ensure_store_dir(workspace_id)
        sources = _read_sources_raw(workspace_id)
        sources.append(rec)
        _write_sources_raw(workspace_id, sources)
        idx = _ensure_index(workspace_id)
        idx["source_count"] = sum(
            1 for s in sources
            if not s.get("deleted", False) and s.get("enabled", True)
        )
        idx["updated_at"] = _now_iso()
        _save_index(workspace_id, idx)
    return {
        "ok": True,
        "summary": f"Imported {rec['source_id']}",
        "source": _public_view(rec, include_content=False),
        "errors": [],
        "warnings": [],
    }


def list_sources(
    workspace_id: str,
    include_disabled: bool = False,
    include_deleted: bool = False,
) -> list:
    """Return public views of all source records (no content).

    Visibility rules:
      - soft-deleted records are excluded unless include_deleted=True
      - disabled (but not deleted) records are excluded unless
        include_disabled=True
    Deleted records always have enabled=False, so the disabled check
    must not exclude them when include_deleted=True.
    """
    if not workspace_id:
        return []
    with _get_lock(workspace_id):
        sources = _read_sources_raw(workspace_id)
    out = []
    for s in sources:
        is_deleted = bool(s.get("deleted", False))
        is_enabled = bool(s.get("enabled", True))
        if is_deleted and not include_deleted:
            continue
        if (not is_enabled) and (not include_disabled) and (not is_deleted):
            continue
        out.append(_public_view(s, include_content=False))
    return out


def read_source(workspace_id: str, source_id: str) -> Optional[dict]:
    """Return full record (incl. content) or None when missing / deleted."""
    if not workspace_id or not source_id:
        return None
    with _get_lock(workspace_id):
        sources = _read_sources_raw(workspace_id)
    for s in sources:
        if s.get("source_id") == source_id:
            if s.get("deleted", False):
                return None
            return _public_view(s, include_content=True)
    return None


def disable_source(workspace_id: str, source_id: str, disabled: bool = True) -> Optional[dict]:
    """Toggle the soft-disable flag. The record stays in storage but
    is excluded from `query` results. Returns the updated public view
    or None when not found."""
    if not workspace_id or not source_id:
        return None
    with _get_lock(workspace_id):
        sources = _read_sources_raw(workspace_id)
        for s in sources:
            if s.get("source_id") == source_id:
                s["enabled"] = not disabled
                s["updated_at"] = _now_iso()
                _write_sources_raw(workspace_id, sources)
                idx = _ensure_index(workspace_id)
                idx["source_count"] = sum(
                    1 for x in sources
                    if not x.get("deleted", False) and x.get("enabled", True)
                )
                idx["updated_at"] = _now_iso()
                _save_index(workspace_id, idx)
                return _public_view(s, include_content=False)
    return None


def delete_source(workspace_id: str, source_id: str) -> bool:
    """Soft-delete a source. The record stays in storage with
    `deleted=True`. Hard-delete is intentionally NOT exposed in the
    public API so that the v1.0 contract keeps an audit trail.

    Returns True if a record was marked, False otherwise.
    """
    if not workspace_id or not source_id:
        return False
    with _get_lock(workspace_id):
        sources = _read_sources_raw(workspace_id)
        changed = False
        for s in sources:
            if s.get("source_id") == source_id:
                s["deleted"] = True
                s["enabled"] = False
                s["updated_at"] = _now_iso()
                changed = True
                break
        if changed:
            _write_sources_raw(workspace_id, sources)
            idx = _ensure_index(workspace_id)
            idx["source_count"] = sum(
                1 for x in sources
                if not x.get("deleted", False) and x.get("enabled", True)
            )
            idx["updated_at"] = _now_iso()
            _save_index(workspace_id, idx)
        return changed


def rename_source(workspace_id: str, source_id: str, title: str) -> Optional[dict]:
    """Rename a knowledge source (update title only).

    Returns the updated public view or None if not found.
    """
    if not workspace_id or not source_id or not title:
        return None
    with _get_lock(workspace_id):
        sources = _read_sources_raw(workspace_id)
        for s in sources:
            if s.get("source_id") == source_id:
                s["title"] = title.strip()
                s["updated_at"] = _now_iso()
                _write_sources_raw(workspace_id, sources)
                return _public_view(s, include_content=False)
    return None


# ── Query scoring ──

_TOKEN_RE = re.compile(r"[\w一-鿿]+", re.UNICODE)
_SNIPPET_MAX = 200


def _tokenize(s: str) -> list:
    return [t.lower() for t in _TOKEN_RE.findall(str(s or ""))]


def _score(query_tokens: list, source: dict) -> float:
    """Lightweight overlap score.

    For each query token:
      - +2.0 if the token appears in `title` (case-insensitive)
      - +1.0 if the token appears in `content`
      - +0.5 if the token appears in `source` label
    Total is normalized by len(query_tokens) so scores are in [0, 3.5].

    This is a deliberately simple, deterministic scoring function. It
    is NOT a vector similarity model. We never fake scores; the score
    is a transparent function of token overlap.
    """
    if not query_tokens:
        return 0.0
    title_tokens = set(_tokenize(source.get("title", "")))
    content_lower = str(source.get("content", "")).lower()
    source_label = str(source.get("source", "")).lower()
    total = 0.0
    for tok in query_tokens:
        t = tok.lower()
        if t in title_tokens:
            total += 2.0
        if t and t in content_lower:
            total += 1.0
        if t and t in source_label:
            total += 0.5
    if not query_tokens:
        return 0.0
    return total / len(query_tokens)


def _build_snippet(content: str, query_tokens: list) -> str:
    """Return a snippet (≤ 200 chars) with a query token in the middle
    if possible; otherwise the head of the content."""
    content = str(content or "")
    if not content:
        return ""
    if not query_tokens:
        return content[:_SNIPPET_MAX]
    lower = content.lower()
    for tok in query_tokens:
        idx = lower.find(tok.lower())
        if idx >= 0:
            start = max(0, idx - 60)
            end = min(len(content), start + _SNIPPET_MAX)
            snippet = content[start:end]
            return snippet
    return content[:_SNIPPET_MAX]


def query(
    workspace_id: str,
    query: str,
    top_k: int = 5,
    filters: Optional[dict] = None,
) -> dict:
    """Search the workspace knowledge store.

    - Only enabled and non-deleted sources are searched.
    - Returns ok=True even when no hits are found (the store is
      honest about emptiness, not fabricated).
    - Returns hits, source_count, source_summary, and metadata.
    """
    if not workspace_id:
        return {"ok": False, "summary": "workspace_id is required",
                "errors": ["missing_workspace_id"],
                "hits": [], "source_count": 0, "source_summary": []}
    query = str(query or "").strip()
    if not query:
        return {"ok": False, "summary": "query is required",
                "errors": ["missing_query"],
                "hits": [], "source_count": 0, "source_summary": []}
    top_k = int(top_k or 5)
    if top_k < 1:
        top_k = 1
    filters = filters or {}
    with _get_lock(workspace_id):
        sources = _read_sources_raw(workspace_id)
    candidates = [s for s in sources
                 if s.get("enabled", True) and not s.get("deleted", False)]
    query_tokens = _tokenize(query)
    # Optional metadata filter (e.g. {"category": "rfc"}).
    if filters:
        candidates = [s for s in candidates
                      if all((s.get("metadata") or {}).get(k) == v
                             for k, v in filters.items())]
    scored = []
    for s in candidates:
        sc = _score(query_tokens, s)
        if sc > 0:
            scored.append((sc, s))
    scored.sort(key=lambda x: (-x[0], x[1].get("created_at", "")))
    hits = []
    for sc, s in scored[:top_k]:
        snippet = _build_snippet(s.get("content", ""), query_tokens)
        hits.append({
            "title": s.get("title", ""),
            "content": s.get("content", "")[:2000],
            "source": s.get("source", "unspecified"),
            "score": round(sc, 3),
            "metadata": {
                "source_id": s.get("source_id", ""),
                "created_at": s.get("created_at", ""),
            },
        })
    summaries = []
    for h in hits[:5]:
        summaries.append({
            "title": h["title"],
            "source": h["source"],
            "score": h["score"],
            "snippet": h["content"][:_SNIPPET_MAX] if h["content"] else "",
        })
    if hits:
        summary = (
            f"找到 {len(hits)} 条与 '{query}' 相关的结果"
            + (f"，来源: {', '.join(h['source'] for h in hits[:3])}" if hits else "")
            + "。"
        )
    else:
        summary = (
            f"知识库中未找到与 '{query}' 相关的结果。请确认已导入相关资料，"
            "或尝试其他关键词。"
        )
    return {
        "ok": True,
        "summary": summary,
        "query": query,
        "hits": hits,
        "source_count": len(hits),
        "source_summary": summaries,
        "warnings": [],
        "errors": [],
        "metadata": {
            "retrieval_backend": "local_store",
            "workspace_id": workspace_id,
            "top_k": top_k,
            "candidate_count": len(candidates),
            "scoring": "token_overlap_v1",
        },
    }


# ── Stats (for diagnostics; not part of the public tool surface) ──

def store_stats(workspace_id: str) -> dict:
    """Return non-sensitive store stats (counts)."""
    if not workspace_id:
        return {"workspace_id": "", "enabled_count": 0,
                "disabled_count": 0, "deleted_count": 0,
                "total_records": 0}
    with _get_lock(workspace_id):
        sources = _read_sources_raw(workspace_id)
    enabled = sum(1 for s in sources
                  if s.get("enabled", True) and not s.get("deleted", False))
    disabled = sum(1 for s in sources
                   if not s.get("enabled", True) and not s.get("deleted", False))
    deleted = sum(1 for s in sources if s.get("deleted", False))
    return {
        "workspace_id": workspace_id,
        "enabled_count": enabled,
        "disabled_count": disabled,
        "deleted_count": deleted,
        "total_records": len(sources),
    }
