# backend/api/workspace_status_routes.py
"""Workspace status and health API routes."""

from __future__ import annotations

from flask import jsonify

from backend.core.responses import error_response, ok_response
from workspace.ids import validate_workspace_id


def register_workspace_status_routes(app):
    """Register workspace status and health routes."""

    @app.route("/api/workspaces/<ws_id>/status")
    def api_workspace_status(ws_id: str):
        try:
            ws_id = validate_workspace_id(ws_id)
        except ValueError:
            body, code = error_response("INVALID_WORKSPACE_ID", "invalid workspace_id", 400)
            return jsonify(body), code

        data: dict = {"workspace_exists": False, "file_count": 0, "artifact_count": 0,
                      "knowledge_source_count": 0, "pcap_session_count": 0,
                      "storage_health": "unknown", "index_health": "unknown"}

        # Check workspace exists
        from storage.paths import workspace_root
        ws = workspace_root(ws_id)
        if not ws.is_dir():
            body, code = error_response("WORKSPACE_NOT_FOUND", "workspace not found", 404)
            return jsonify(body), code
        data["workspace_exists"] = True

        # File count
        try:
            from storage.file_store import list_files
            data["file_count"] = len(list_files(ws_id, lifecycle=""))
        except Exception:
            pass

        # Artifact count
        try:
            from artifacts.store import list_artifacts
            data["artifact_count"] = len(list_artifacts(ws_id, limit=10000))
        except Exception:
            pass

        # Knowledge source count
        try:
            from agent.modules.knowledge.service import list_sources
            sources = list_sources(ws_id)
            data["knowledge_source_count"] = len(sources.get("sources", []))
        except Exception:
            pass

        # PCAP session count
        try:
            idx_path = ws / "index" / "pcap_sessions.jsonl"
            if idx_path.exists():
                lines = [l for l in idx_path.read_text(encoding="utf-8").strip().split("\n") if l.strip()]
                data["pcap_session_count"] = len(lines)
        except Exception:
            pass

        # Index health
        for idx_name in ("files.jsonl", "references.jsonl", "artifacts.jsonl"):
            idx = ws / "index" / idx_name
            if idx.exists() and idx.is_file():
                data["index_health"] = "ok"
                break
        else:
            data["index_health"] = "missing"

        # Storage health
        if data["file_count"] > 0 or data["index_health"] == "ok":
            data["storage_health"] = "ok"
        else:
            data["storage_health"] = "no_data"

        body, code = ok_response(data, workspace_id=ws_id)
        return jsonify(body), code


    @app.route("/api/workspaces/<ws_id>/storage/health")
    def api_storage_health(ws_id: str):
        try:
            ws_id = validate_workspace_id(ws_id)
        except ValueError:
            body, code = error_response("INVALID_WORKSPACE_ID", "invalid workspace_id", 400)
            return jsonify(body), code

        try:
            from storage.doctor import run_doctor
            result = run_doctor(ws_id)
            body, code = ok_response(result, workspace_id=ws_id)
            return jsonify(body), code
        except Exception as exc:
            body, code = error_response("INTERNAL_ERROR", str(exc)[:200], 500)
            return jsonify(body), code
