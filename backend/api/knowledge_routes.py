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

    # ── Source Management ──
    @app.route("/api/knowledge/sources")
    def api_knowledge_sources():
        ws_id = request.args.get("workspace_id", "default")
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        from knowledge.store import list_sources, get_source_count
        status = request.args.get("status")
        sources = list_sources(ws_id, status=status)
        counts = get_source_count(ws_id)
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
        return jsonify({"ok": True, "source": source.safe_dict()})

    @app.route("/api/knowledge/sources/<source_id>/reindex", methods=["POST"])
    def api_knowledge_reindex(source_id):
        ws_id = request.args.get("workspace_id", "default")
        if request.is_json:
            ws_id = request.get_json(silent=True).get("workspace_id", ws_id)
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        from knowledge.indexer import reindex_source
        source = reindex_source(ws_id, source_id)
        if not source:
            return jsonify({"ok": False, "error": "source_not_found_or_indexing_failed"}), 404
        return jsonify({"ok": True, "source": source.safe_dict()})

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
        return jsonify({
            "ok": True,
            "results": [r.as_dict() for r in results],
            "count": len(results),
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
