# backend/api/reference_routes.py
"""ReferenceIndex read API routes."""

from __future__ import annotations

from typing import Any

from flask import jsonify, request


def _validated_ws_id(raw: str = "default") -> tuple:
    from workspace.ids import validate_workspace_id
    try:
        return validate_workspace_id(raw or "default"), None
    except ValueError:
        return None, jsonify({"ok": False, "error": "invalid_workspace_id"}), 400


def register_reference_routes(app):
    """Register ReferenceIndex API routes."""

    @app.route("/api/workspaces/<ws_id>/files/<file_id>/references")
    def api_file_references(ws_id: str, file_id: str):
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        from storage.reference_index import list_references_for_file
        refs = list_references_for_file(ws_id, file_id)
        return jsonify({"ok": True, "workspace_id": ws_id, "file_id": file_id,
                        "references": refs, "count": len(refs)})

    @app.route("/api/workspaces/<ws_id>/artifacts/<artifact_id>/references")
    def api_artifact_references(ws_id: str, artifact_id: str):
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        from storage.reference_index import list_references_for_owner
        refs = list_references_for_owner(ws_id, "artifact", artifact_id)
        return jsonify({"ok": True, "workspace_id": ws_id, "artifact_id": artifact_id,
                        "references": refs, "count": len(refs)})

    @app.route("/api/workspaces/<ws_id>/reference-graph")
    def api_reference_graph(ws_id: str):
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        import json
        from storage.reference_index import _ref_index_path
        idx = _ref_index_path(ws_id)
        refs = []
        if idx.exists():
            for line in idx.read_text(encoding="utf-8").strip().split("\n"):
                if not line.strip():
                    continue
                try:
                    refs.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        nodes: list[dict] = []
        edges: list[dict] = []
        seen: set[str] = set()
        for r in refs:
            fid = r.get("file_id", "")
            oid = f"{r.get('owner_type', '')}:{r.get('owner_id', '')}"
            if fid not in seen:
                seen.add(fid)
                nodes.append({"id": fid, "type": "file"})
            if oid not in seen:
                seen.add(oid)
                nodes.append({"id": oid, "type": r.get("owner_type", "")})
            edges.append({"source": fid, "target": oid, "relation": r.get("relation", "")})
        return jsonify({"ok": True, "workspace_id": ws_id,
                        "nodes": nodes, "edges": edges, "count": len(edges)})
