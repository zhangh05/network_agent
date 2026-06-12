# backend/api/knowledge_routes.py
"""Knowledge Index API routes — search, source management."""

from flask import jsonify, request
from workspace.ids import validate_workspace_id


def _invalid_ws():
    return jsonify({"ok": False, "error": "invalid_workspace_id"}), 400


def _validated_ws_id(raw="default"):
    try:
        return validate_workspace_id(raw or "default"), None
    except ValueError:
        return None, _invalid_ws()


def register_knowledge_routes(app):
    """Register all knowledge API routes on the Flask app."""

    @app.route("/api/knowledge/upload", methods=["POST"])
    def api_knowledge_upload():
        ws_id = request.form.get("workspace_id", "default")
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        if "file" not in request.files:
            return jsonify({"ok": False, "error": "no file provided"}), 400
        uploaded = request.files["file"]
        if not uploaded.filename:
            return jsonify({"ok": False, "error": "empty filename"}), 400

        import re
        from agent.modules.knowledge.ingestion import _ws_root
        safe_name = re.sub(r"[^a-zA-Z0-9_.-]", "_", uploaded.filename)[:120] or "upload.txt"
        upload_dir = _ws_root() / ws_id / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        target = upload_dir / safe_name
        uploaded.save(str(target))

        try:
            tags = [
                t.strip()
                for t in (request.form.get("tags", "") or "").split(",")
                if t.strip()
            ]
            from agent.modules.knowledge.service import import_file
            result = import_file(
                workspace_id=ws_id,
                source=str(target),
                title=request.form.get("title", "") or uploaded.filename,
                source_type=request.form.get("source_type", "project_doc") or "project_doc",
                scope=request.form.get("scope", "workspace") or "workspace",
                language=request.form.get("language", "zh") or "zh",
                tags=tags,
                metadata={"uploaded_filename": uploaded.filename},
            )
        finally:
            try:
                target.unlink()
            except Exception:
                pass

        if not result.get("ok"):
            return jsonify({
                "ok": False,
                "error": (result.get("errors") or ["import_failed"])[0],
                "summary": result.get("summary", "知识库导入失败"),
                "errors": result.get("errors", []),
                "warnings": result.get("warnings", []),
            }), 400

        source = {
            "source_id": result.get("source_id", ""),
            "workspace_id": ws_id,
            "title": result.get("title", "") or request.form.get("title", "") or uploaded.filename,
            "source_type": result.get("source_type", request.form.get("source_type", "project_doc")),
            "scope": result.get("scope", request.form.get("scope", "workspace")),
            "language": result.get("language", request.form.get("language", "zh")),
            "format": result.get("format", ""),
            "chunk_count": result.get("chunk_count", 0),
            "parent_count": result.get("parent_count", 0),
            "status": "indexed",
            "enabled": True,
            "tags": tags,
            "warnings": result.get("warnings", []),
        }
        return jsonify({
            "ok": True,
            "summary": result.get("summary", ""),
            "source": source,
        })

    # ── Source Management ──
    @app.route("/api/knowledge/sources")
    def api_knowledge_sources():
        ws_id = request.args.get("workspace_id", "default")
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        from knowledge.store import list_sources
        status = request.args.get("status")
        sources = list_sources(ws_id, status=status)
        sources.extend(_module_sources(ws_id, status=status))
        # Filter out sources whose artifacts have been deleted
        sources = _filter_deleted_artifact_sources(ws_id, sources)
        # Recalculate counts after filtering
        counts = {
            "total": len(sources),
            "indexed": sum(1 for s in sources if s.get("status") == "indexed"),
            "pending": sum(1 for s in sources if s.get("status") == "pending"),
            "indexing": sum(1 for s in sources if s.get("status") == "indexing"),
            "failed": sum(1 for s in sources if s.get("status") == "failed"),
        }
        return jsonify({"ok": True, "sources": sources, "counts": counts})

    @app.route("/api/knowledge/sources/from-artifact", methods=["POST"])
    def api_knowledge_from_artifact():
        data = request.get_json(silent=True) or {}
        ws_id = data.get("workspace_id", "default")
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        artifact_id = data.get("artifact_id", "").strip()
        if not artifact_id:
            return jsonify({"ok": False, "error": "artifact_id required"}), 400

        from knowledge.indexer import index_artifact
        source = index_artifact(ws_id, artifact_id)
        if not source:
            # Check if artifact exists and why it failed
            from artifacts.store import get_artifact
            from knowledge.policy import can_index
            art = get_artifact(ws_id, artifact_id)
            if not art:
                return jsonify({"ok": False, "error": "artifact_not_found"}), 404
            allowed, reason = can_index(art.as_dict() if hasattr(art, 'as_dict') else art.__dict__)
            if not allowed:
                return jsonify({"ok": False, "error": reason}), 422
            return jsonify({"ok": False, "error": "indexing_failed"}), 500
        return jsonify({"ok": True, "source": source.as_dict()})

    @app.route("/api/knowledge/sources/<source_id>/reindex", methods=["POST"])
    def api_knowledge_reindex(source_id):
        ws_id = request.args.get("workspace_id", "default")
        if request.is_json:
            ws_id = request.get_json(silent=True).get("workspace_id", ws_id)
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        # Try legacy store first
        from knowledge.indexer import reindex_source as legacy_reindex
        source = legacy_reindex(ws_id, source_id)
        if source is not None:
            return jsonify({"ok": True, "source": source.as_dict()})
        # Try v2 store (ksrc_* prefix)
        from agent.modules.knowledge.service import reindex_source as v2_reindex
        try:
            result = v2_reindex(ws_id, source_id)
            if result and isinstance(result, dict):
                ok = result.get("ok", False)
                if not ok:
                    return jsonify(result), 500
                # v2 reindex returns dict with source_id; re-fetch full source
                from agent.modules.knowledge.service import list_sources as v2_list
                all_src = v2_list(ws_id)
                v2_sources = all_src.get("sources", []) if isinstance(all_src, dict) else []
                for s in v2_sources:
                    sid = s.source_id if hasattr(s, "source_id") else s.get("source_id", "")
                    if sid == source_id:
                        sd = s.as_dict() if hasattr(s, "as_dict") else s
                        return jsonify({"ok": True, "source": sd})
                # Not found in refreshed list, return raw result
                return jsonify({"ok": True, "source": result})
        except Exception:
            pass
        return jsonify({"ok": False, "error": "source_not_found_or_indexing_failed"}), 404

    # ── Delete ──
    @app.route("/api/knowledge/sources/<source_id>", methods=["DELETE"])
    def api_knowledge_delete_source(source_id):
        ws_id = request.args.get("workspace_id", "default")
        if request.is_json:
            ws_id = request.get_json(silent=True).get("workspace_id", ws_id)
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        # Try v2 store first
        from agent.modules.knowledge.service import delete_source
        result = delete_source(ws_id, source_id)
        if result.get("ok"):
            return jsonify(result)
        # Fall back to legacy knowledge store
        try:
            from knowledge.store import delete_source as legacy_delete
            ok = legacy_delete(ws_id, source_id)
            if ok:
                return jsonify({"ok": True, "source_id": source_id, "summary": f"deleted {source_id}"})
        except Exception:
            pass
        return jsonify(result), 404

    # ── Rename ──
    @app.route("/api/knowledge/sources/<source_id>", methods=["PATCH"])
    def api_knowledge_rename_source(source_id):
        data = request.get_json(silent=True) or {}
        ws_id = data.get("workspace_id", "default")
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        title = (data.get("title") or "").strip()
        if not title:
            return jsonify({"ok": False, "error": "title required"}), 400
        # Try v2 store first — directly update the JSONL source file
        import json as _json, pathlib as _pl
        from agent.modules.knowledge.store import _sources_path, _read_sources_raw, _write_sources_raw
        try:
            sources = _read_sources_raw(ws_id)
            found = False
            for i, s in enumerate(sources):
                sid = s.get("source_id", "")
                if sid == source_id:
                    sources[i]["title"] = title
                    sources[i]["updated_at"] = __import__("time").strftime("%Y-%m-%dT%H:%M:%S")
                    found = True
                    break
            if found:
                _write_sources_raw(ws_id, sources)
                # Build a response dict from the updated record
                result_src = {k: v for k, v in sources[i].items() if k != "content"}
                result_src["ok"] = True
                return jsonify({"ok": True, "source": result_src})
        except Exception:
            pass
        # If not found in v2, try legacy store
        try:
            from knowledge.store import get_source, save_source
            from knowledge.schemas import KnowledgeSource
            rec = get_source(ws_id, source_id)
            if not rec:
                return jsonify({"ok": False, "error": "source_not_found"}), 404
            rec["title"] = title
            ks = KnowledgeSource(**rec)
            save_source(ks)
            return jsonify({"ok": True, "source": ks.as_dict()})
        except Exception as e:
            return jsonify({"ok": False, "error": f"rename failed: {str(e)[:200]}"}), 500

    # ── Detail ──
    @app.route("/api/knowledge/sources/<source_id>", methods=["GET"])
    def api_knowledge_get_source(source_id):
        ws_id = request.args.get("workspace_id", "default")
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        # Try v2 store first
        from agent.modules.knowledge.store import list_sources as v2_list
        v2 = v2_list(ws_id, include_deleted=True)
        for s in v2:
            sid = s.source_id if hasattr(s, "source_id") else s.get("source_id", "")
            if sid == source_id:
                sd = s.as_dict() if hasattr(s, "as_dict") else s
                # Attach full text content if available
                if hasattr(s, "chunk_ids") and s.chunk_ids:
                    from agent.modules.knowledge.store import list_chunks
                    chunks = list_chunks(ws_id, source_id=source_id, limit=50)
                    if isinstance(chunks, list):
                        sd["chunks"] = [_chunk_dict(c) for c in chunks]
                return jsonify({"ok": True, "source": sd})
        # Try legacy store
        try:
            from knowledge.store import get_source
            rec = get_source(ws_id, source_id)
            if not rec:
                return jsonify({"ok": False, "error": "source_not_found"}), 404
            from knowledge.store import list_chunks
            chunks = list_chunks(ws_id, source_id=source_id)
            rec["chunks"] = chunks or []
            return jsonify({"ok": True, "source": rec})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)[:200]}), 500

    # ── Search ──
    @app.route("/api/knowledge/search")
    def api_knowledge_search():
        ws_id = request.args.get("workspace_id", "default")
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        query = request.args.get("q", "").strip()
        artifact_type = request.args.get("artifact_type")
        sensitivity = request.args.get("sensitivity")
        source_id = request.args.get("source_id")
        artifact_id = request.args.get("artifact_id")
        try:
            limit = min(int(request.args.get("limit", 20)), 100)
        except ValueError:
            return jsonify({"ok": False, "error": "invalid_limit"}), 400

        from knowledge.search import search
        results = search(
            workspace_id=ws_id,
            query=query,
            artifact_type=artifact_type,
            sensitivity=sensitivity,
            source_id=source_id,
            artifact_id=artifact_id,
            limit=limit,
        )
        module_results = _module_search_results(
            workspace_id=ws_id,
            query=query,
            source_id=source_id,
            limit=limit,
        )
        merged = [r.as_dict() for r in results]
        seen = {r.get("chunk_id") for r in merged}
        for r in module_results:
            if r.get("chunk_id") not in seen:
                merged.append(r)
                seen.add(r.get("chunk_id"))
        merged = merged[:limit]
        return jsonify({
            "ok": True,
            "results": merged,
            "count": len(merged),
            "query": query,
            "note": "搜索结果为安全摘录，不是完整文件内容。不包含配置详情、密钥或绝对路径。",
        })

    # ── Chunk Detail ──
    @app.route("/api/knowledge/chunks/<chunk_id>")
    def api_knowledge_chunk(chunk_id):
        ws_id = request.args.get("workspace_id", "default")
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        from knowledge.store import get_chunk
        chunk = get_chunk(ws_id, chunk_id)
        if not chunk:
            try:
                from agent.modules.knowledge.index import get_chunk as get_module_chunk
                module_chunk = get_module_chunk(ws_id, chunk_id)
                chunk = _module_chunk_to_safe_dict(module_chunk.to_dict()) if module_chunk else None
            except Exception:
                chunk = None
        if not chunk:
            return jsonify({"ok": False, "error": "chunk_not_found"}), 404
        # Only return safe fields
        safe = {
            "chunk_id": chunk.get("chunk_id"), "source_id": chunk.get("source_id"),
            "artifact_id": chunk.get("artifact_id"), "title": chunk.get("title"),
            "summary": chunk.get("summary"), "safe_excerpt": chunk.get("safe_excerpt"),
            "sensitivity": chunk.get("sensitivity"),
            "artifact_type": chunk.get("artifact_type"),
            "tags": chunk.get("tags"), "chunk_index": chunk.get("chunk_index"),
            "llm_safe": chunk.get("llm_safe"), "created_at": chunk.get("created_at"),
        }
        return jsonify({"ok": True, "chunk": safe})


def _filter_deleted_artifact_sources(workspace_id: str, sources: list) -> list:
    """Filter out knowledge sources whose artifacts have been deleted.
    
    Ensures knowledge index doesn't show orphaned entries for deleted artifacts.
    """
    try:
        from artifacts.store import get_artifact
    except ImportError:
        return sources
    filtered = []
    for s in sources:
        artifact_id = s.get("artifact_id", "")
        if not artifact_id:
            filtered.append(s)
            continue
        art = get_artifact(workspace_id, artifact_id)
        # Only remove source if artifact exists AND is explicitly deleted
        # If artifact not found, keep source (could be in a test workspace)
        if art is not None and getattr(art, "lifecycle", "active") == "deleted":
            continue
        filtered.append(s)
    return filtered


def _module_sources(workspace_id: str, status: str = None) -> list:
    """Return sources from the v1.0.1 document knowledge store.

    This keeps the public API compatible while direct file uploads use the
    richer parser/chunker pipeline under agent.modules.knowledge.
    """
    try:
        from agent.modules.knowledge.service import list_sources, list_chunks
        src_result = list_sources(workspace_id)
        chunks_result = list_chunks(workspace_id, limit=500)
    except Exception:
        return []
    chunks = chunks_result.get("chunks", []) if isinstance(chunks_result, dict) else []
    child_counts = {}
    for c in chunks:
        if c.get("chunk_type") == "parent":
            continue
        sid = c.get("source_id", "")
        child_counts[sid] = child_counts.get(sid, 0) + 1

    out = []
    for s in src_result.get("sources", []):
        meta = s.get("metadata", {}) or {}
        if meta.get("hidden"):
            continue
        source_status = "indexed" if s.get("enabled", True) and not s.get("deleted", False) else "disabled"
        if status and source_status != status:
            continue
        out.append({
            "source_id": s.get("source_id", ""),
            "workspace_id": workspace_id,
            "title": s.get("title", ""),
            "source_type": meta.get("source_type", s.get("source", "")),
            "status": source_status,
            "enabled": bool(s.get("enabled", True)),
            "chunk_count": child_counts.get(s.get("source_id", ""), 0),
            "language": meta.get("language", ""),
            "tags": list(meta.get("tags") or []),
            "created_at": s.get("created_at", ""),
            "updated_at": s.get("updated_at", ""),
            "metadata": {
                "format": meta.get("format", ""),
                "scope": meta.get("scope", "workspace"),
            },
        })
    return out


def _module_search_results(workspace_id: str, query: str, source_id: str = "", limit: int = 20) -> list:
    try:
        from agent.modules.knowledge.service import search_chunks
        result = search_chunks(
            workspace_id=workspace_id,
            query=query,
            top_k=limit,
            source_id=source_id or "",
        )
    except Exception:
        return []
    hits = result.get("hits", []) if isinstance(result, dict) else []
    if not hits and query:
        hits = _module_title_search(workspace_id, query, source_id=source_id, limit=limit)
    out = []
    for h in hits:
        if (h.get("metadata") or {}).get("hidden"):
            continue
        snippet = h.get("snippet", "")
        out.append({
            "chunk_id": h.get("chunk_id", ""),
            "source_id": h.get("source_id", ""),
            "artifact_id": "",
            "title": h.get("title", ""),
            "artifact_name": h.get("title", ""),
            "summary": h.get("chapter", "") or h.get("section", ""),
            "safe_excerpt": snippet,
            "artifact_type": "",
            "sensitivity": "internal",
            "tags": list((h.get("metadata") or {}).get("tags") or []),
            "score": round(float(h.get("score", 0) or 0), 3),
            "source_ref": f"knowledge:{h.get('source_id', '')}",
            "llm_safe": True,
        })
    return out


def _module_title_search(workspace_id: str, query: str, source_id: str = "", limit: int = 20) -> list:
    """Fallback for document-title/chapter searches.

    The module retriever intentionally filters title-only hits when the body
    has no supporting match. Public library search should still find a
    document by title, so this fallback returns safe excerpts from matching
    chunks without exposing full file paths or raw metadata.
    """
    try:
        from agent.modules.knowledge.index import load_all_chunks
        chunks = load_all_chunks(workspace_id)
    except Exception:
        return []
    q = str(query or "").lower().strip()
    if not q:
        return []
    out = []
    for c in chunks:
        if source_id and c.source_id != source_id:
            continue
        if c.chunk_type == "parent":
            continue
        meta = c.metadata or {}
        haystack = " ".join([
            str(meta.get("source_title", "")),
            str(c.chapter or ""),
            str(c.section or ""),
            str(c.subsection or ""),
            str(c.index_text or ""),
        ]).lower()
        if q not in haystack:
            continue
        out.append({
            "chunk_id": c.chunk_id,
            "source_id": c.source_id,
            "parent_chunk_id": c.parent_chunk_id,
            "title": meta.get("source_title", "") or c.chapter,
            "chapter": c.chapter,
            "section": c.section,
            "snippet": (c.content or c.chapter or meta.get("source_title", ""))[:200],
            "score": 0.5,
            "metadata": {
                "source_type": meta.get("source_type", ""),
                "tags": list(meta.get("tags") or []),
            },
        })
        if len(out) >= limit:
            break
    return out


def _chunk_dict(obj) -> dict:
    """Convert a chunk object to a safe dict, handling both dataclass and dict."""
    if hasattr(obj, "as_dict"):
        return obj.as_dict()
    if isinstance(obj, dict):
        return obj
    return {}


def _module_chunk_to_safe_dict(chunk: dict) -> dict:
    meta = chunk.get("metadata", {}) or {}
    return {
        "chunk_id": chunk.get("chunk_id"),
        "source_id": chunk.get("source_id"),
        "artifact_id": "",
        "title": meta.get("source_title", ""),
        "summary": chunk.get("chapter", "") or chunk.get("section", ""),
        "safe_excerpt": chunk.get("content", "")[:900],
        "sensitivity": "internal",
        "artifact_type": "",
        "tags": list(meta.get("tags") or []),
        "chunk_index": chunk.get("chunk_index"),
        "llm_safe": True,
        "created_at": chunk.get("created_at"),
    }
