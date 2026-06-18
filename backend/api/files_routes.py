"""Unified files management API — single storage layer for all file types.

Types: memory | knowledge | artifact | pcap | pcap_analysis
"""

import json
import os
import uuid
import shutil
from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, request, jsonify

from agent.modules.knowledge.ingestion import _ws_root

FILES_BP = Blueprint("files", __name__)


# ── Helpers ──────────────────────────────────────────────────────────

# Source-based subdirectories under files/
KNOWN_SOURCES = ["upload", "agent"]

def _files_dir(workspace_id: str = "default") -> Path:
    return _ws_root() / workspace_id / "files"


def _source_dir(workspace_id: str, source: str) -> Path:
    return _files_dir(workspace_id) / source


def _record_path(workspace_id: str, file_id: str) -> Path:
    """Find record.json by scanning source subdirs."""
    for src in KNOWN_SOURCES:
        p = _source_dir(workspace_id, src) / file_id / "record.json"
        if p.exists():
            return p
    # Default: upload
    return _source_dir(workspace_id, "upload") / file_id / "record.json"


def _content_dir(workspace_id: str, file_id: str) -> Path:
    """Get content directory for existing file. NB: caller should mkdir."""
    for src in KNOWN_SOURCES:
        p = _source_dir(workspace_id, src) / file_id / "content"
        if p.exists():
            return p
    return _source_dir(workspace_id, "upload") / file_id / "content"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_record(workspace_id: str, file_id: str) -> dict | None:
    p = _record_path(workspace_id, file_id)
    if not p.exists():
        return None
    return json.loads(p.read_text())


def _write_record(workspace_id: str, file_id: str, record: dict):
    src = record.get("source", "upload")
    if src not in KNOWN_SOURCES:
        src = "upload"
    p = _source_dir(workspace_id, src) / file_id / "record.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(record, ensure_ascii=False, indent=2))


def _list_records(workspace_id: str, file_type: str | None = None) -> list[dict]:
    base = _files_dir(workspace_id)
    records = []
    seen = set()

    # 1. File system records (upload / agent)
    if base.exists():
        for src in KNOWN_SOURCES:
            sd = base / src
            if not sd.is_dir():
                continue
            for dir_path in sorted(sd.iterdir()):
                if not dir_path.is_dir():
                    continue
                rp = dir_path / "record.json"
                if not rp.exists():
                    continue
                try:
                    rec = json.loads(rp.read_text())
                except Exception:
                    continue
                fid = rec.get("file_id") or dir_path.name
                if fid in seen:
                    continue
                seen.add(fid)
                ca = rec.get("created_at")
                if isinstance(ca, (int, float)) and ca > 1000000000:
                    from datetime import datetime, timezone
                    rec["created_at"] = datetime.fromtimestamp(ca, tz=timezone.utc).isoformat()
                if rec.get("hidden"):
                    continue
                if rec.get("source") == "migration":
                    continue
                if rec.get("type") in ("output",):
                    continue
                if file_type and rec.get("type") != file_type:
                    continue
                records.append(rec)

    # 2. ContextStore knowledge sources (type="knowledge")
    if file_type in (None, "knowledge"):
        try:
            from context.context_store import get_context_store
            store = get_context_store(workspace_id)
            sources = store.list_items(item_type="knowledge_source", limit=999)
            for s in sources:
                meta = s.get("metadata", {}) or {}
                if meta.get("hidden"):
                    continue
                sid = s.get("source_id", s.get("item_id", ""))
                if sid in seen:
                    continue
                seen.add(sid)
                records.append({
                    "file_id": sid,
                    "type": "knowledge",
                    "title": s.get("title", ""),
                    "filename": "",
                    "mime_type": meta.get("format", "text/plain"),
                    "size": len(s.get("content", "")),
                    "tags": list(s.get("tags") or []),
                    "workspace_id": workspace_id,
                    "source": "context_store",
                    "indexed": True,
                    "parent_id": None,
                    "metadata": {
                        "source_type": meta.get("source_type", ""),
                        "chunk_count": meta.get("chunk_count", 0),
                        "language": meta.get("language", ""),
                    },
                    "created_at": s.get("created_at", ""),
                    "updated_at": meta.get("updated_at", s.get("created_at", "")),
                })
        except Exception:
            pass

    # 3. ContextStore memory records (type="memory")
    if file_type in (None, "memory"):
        try:
            from context.context_store import get_context_store
            store = get_context_store(workspace_id)
            mems = store.list_items(item_type="memory_hit", limit=999)
            for m in mems:
                mid = m.get("item_id", m.get("memory_id", ""))
                if mid in seen:
                    continue
                seen.add(mid)
                records.append({
                    "file_id": mid,
                    "type": "memory",
                    "title": m.get("title", ""),
                    "filename": "",
                    "mime_type": "text/plain",
                    "size": len(m.get("content", "")),
                    "tags": list(m.get("tags") or [])[:5],
                    "workspace_id": workspace_id,
                    "source": "context_store",
                    "indexed": False,
                    "parent_id": None,
                    "metadata": {
                        "memory_type": m.get("memory_type", ""),
                        "scope": m.get("scope", ""),
                        "confidence": m.get("confidence", ""),
                    },
                    "created_at": m.get("created_at", ""),
                    "updated_at": m.get("created_at", ""),
                })
        except Exception:
            pass

    return sorted(records, key=lambda r: str(r.get("created_at", "")), reverse=True)


# ── CRUD Routes ──────────────────────────────────────────────────────

@FILES_BP.route("/api/files", methods=["GET"])
def list_files():
    """GET /api/files?type=pcap&workspace_id=default"""
    ws_id = request.args.get("workspace_id", "default")
    file_type = request.args.get("type") or None
    records = _list_records(ws_id, file_type)
    return jsonify({"ok": True, "files": records, "count": len(records)})


@FILES_BP.route("/api/files/<file_id>", methods=["GET"])
def get_file(file_id: str):
    """GET /api/files/:id — from filesystem or ContextStore."""
    ws_id = request.args.get("workspace_id", "default")
    rec = _read_record(ws_id, file_id)
    if rec:
        return jsonify({"ok": True, **rec})
    # Fallback: ContextStore
    try:
        from context.context_store import get_context_store
        store = get_context_store(ws_id)
        item = store.get(file_id)
        if not item and not file_id.startswith("mem_"):
            item = store.get(f"mem_{file_id}")
        if not item and not file_id.startswith("kc_"):
            item = store.get(f"kc_{file_id}")
        if item:
            return jsonify({
                "ok": True,
                "file_id": file_id,
                "type": "knowledge" if item.get("item_type") == "knowledge_source" else "memory",
                "title": item.get("title", ""),
                "source": "context_store",
                "metadata": item.get("metadata", {}),
                "created_at": item.get("created_at", ""),
            })
    except Exception:
        pass
    return jsonify({"ok": False, "error": "not found"}), 404


@FILES_BP.route("/api/files", methods=["POST"])
def create_file():
    """POST /api/files — create file record + optional upload."""
    ws_id = request.form.get("workspace_id", "default")
    file_type = request.form.get("type", "raw")
    title = request.form.get("title", "")
    tags_str = request.form.get("tags", "")
    parent_id = request.form.get("parent_id") or None
    aux = request.form.get("aux", "{}")

    file_id = f"f_{uuid.uuid4().hex[:12]}"
    now = _now_iso()

    # Build record
    record: dict = {
        "file_id": file_id,
        "type": file_type,
        "title": title,
        "filename": "",
        "mime_type": "",
        "size": 0,
        "tags": [t.strip() for t in tags_str.split(",") if t.strip()],
        "workspace_id": ws_id,
        "source": "upload",
        "indexed": False,
        "parent_id": parent_id,
        "metadata": {},
        "created_at": now,
        "updated_at": now,
    }

    # Handle file upload
    uploaded = request.files.get("file")
    if uploaded and uploaded.filename:
        safe_name = _safe_filename(uploaded.filename)
        content_dir = _content_dir(ws_id, file_id)
        content_dir.mkdir(parents=True, exist_ok=True)
        target = content_dir / safe_name
        uploaded.save(str(target))
        record["filename"] = safe_name
        record["mime_type"] = uploaded.content_type or ""
        record["size"] = target.stat().st_size

    # Handle body-only create (JSON)
    elif request.is_json:
        body = request.get_json(force=True)
        ws_id = body.get("workspace_id", ws_id) or "default"
        record["workspace_id"] = ws_id
        record["title"] = body.get("title", record["title"])
        record["type"] = body.get("type", record["type"])
        record["tags"] = body.get("tags", record["tags"])
        record["parent_id"] = body.get("parent_id", record["parent_id"])
        record["metadata"] = body.get("metadata", {})
        record["source"] = body.get("source", "agent")
        # Also update hidden flag if present
        if "hidden" in body:
            record["hidden"] = body["hidden"]
        # Write content if provided — use source-aware dir
        if body.get("content"):
            src = record.get("source", "upload")
            if src not in KNOWN_SOURCES:
                src = "upload"
            content_dir = _source_dir(ws_id, src) / file_id / "content"
            content_dir.mkdir(parents=True, exist_ok=True)
            ext = body.get("extension", "txt")
            fpath = content_dir / f"content.{ext}"
            fpath.write_text(str(body["content"]), encoding="utf-8")
            record["filename"] = f"content.{ext}"
            record["mime_type"] = f"text/{ext}"
            record["size"] = fpath.stat().st_size

    if not request.is_json:
        try:
            record["metadata"] = json.loads(aux) if isinstance(aux, str) else aux
        except Exception:
            record["metadata"] = {}

    _write_record(ws_id, file_id, record)
    return jsonify({"ok": True, **record})


@FILES_BP.route("/api/files/<file_id>", methods=["PUT"])
def update_file(file_id: str):
    """PUT /api/files/:id — update record fields."""
    ws_id = request.args.get("workspace_id", "default")
    rec = _read_record(ws_id, file_id)
    if not rec:
        return jsonify({"ok": False, "error": "not found"}), 404

    body = request.get_json(force=True) if request.is_json else {}
    for field in ("title", "tags", "metadata", "indexed"):
        if field in body:
            rec[field] = body[field]
    rec["updated_at"] = _now_iso()
    _write_record(ws_id, file_id, rec)
    return jsonify({"ok": True, **rec})


@FILES_BP.route("/api/files/<file_id>", methods=["DELETE"])
def delete_file(file_id: str):
    """DELETE /api/files/:id — delete from filesystem or ContextStore."""
    ws_id = request.args.get("workspace_id", "default")

    # 1. Try filesystem (files/ directory)
    rec = _read_record(ws_id, file_id)
    if rec:
        for src in KNOWN_SOURCES:
            shutil.rmtree(_source_dir(ws_id, src) / file_id, ignore_errors=True)
        return jsonify({"ok": True, "deleted": file_id})

    # 2. Try ContextStore (knowledge_source or memory_hit)
    try:
        from context.context_store import get_context_store
        store = get_context_store(ws_id)
        item = store.get(file_id)
        # Fallback: try with mem_ prefix for memory items
        if not item and not file_id.startswith("mem_"):
            item = store.get(f"mem_{file_id}")
        if not item and not file_id.startswith("kc_"):
            item = store.get(f"kc_{file_id}")
        if item:
            item_type = item.get("item_type", "")
            actual_id = item.get("item_id", file_id)
            store.delete(actual_id)

            # If knowledge_source, also delete associated chunks
            if item_type == "knowledge_source":
                chunks = store.list_items(
                    item_type="knowledge_chunk",
                    source_id=actual_id,
                    limit=9999,
                )
                for c in chunks:
                    store.delete(c["item_id"])
                return jsonify({
                    "ok": True,
                    "deleted": file_id,
                    "chunks_deleted": len(chunks),
                })

            return jsonify({"ok": True, "deleted": file_id})
    except Exception:
        pass

    return jsonify({"ok": False, "error": "not found"}), 404


@FILES_BP.route("/api/files/<file_id>/content", methods=["GET"])
def get_file_content(file_id: str):
    """GET /api/files/:id/content — from filesystem or ContextStore."""
    ws_id = request.args.get("workspace_id", "default")

    # 1. Try filesystem
    rec = _read_record(ws_id, file_id)
    if rec and rec.get("filename"):
        cpath = _content_dir(ws_id, file_id) / rec["filename"]
        if cpath.exists():
            if rec.get("mime_type", "").startswith("text/"):
                return jsonify({"ok": True, "content": cpath.read_text(encoding="utf-8", errors="replace")})
            return jsonify({"ok": True, "filepath": str(cpath), "size": cpath.stat().st_size})

    # 2. Try ContextStore
    try:
        from context.context_store import get_context_store
        store = get_context_store(ws_id)
        item = store.get(file_id)
        if not item and not file_id.startswith("mem_"):
            item = store.get(f"mem_{file_id}")
        if not item and not file_id.startswith("kc_"):
            item = store.get(f"kc_{file_id}")
        if item:
            content = item.get("content", "")
            if isinstance(content, dict):
                import json as _json
                content = _json.dumps(content, ensure_ascii=False, indent=2)
            return jsonify({"ok": True, "content": str(content)})
    except Exception:
        pass

    return jsonify({"ok": False, "error": "no content"}), 404


def _safe_filename(name: str) -> str:
    import re
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", name)[:120] or "file"


def register_files_routes(app):
    app.register_blueprint(FILES_BP)
