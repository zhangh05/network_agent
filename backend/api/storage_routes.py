"""Unified managed-file metadata and event APIs."""

from __future__ import annotations

from flask import Response, jsonify, request, stream_with_context

from workspace.ids import validate_workspace_id


def register_storage_routes(app) -> None:
    @app.route("/api/storage/files")
    def api_storage_files():
        try:
            workspace_id = validate_workspace_id(request.args.get("workspace_id", ""))
        except ValueError:
            return jsonify({"ok": False, "error": "invalid_workspace_id"}), 400
        logical_type = request.args.get("logical_type", "").strip()
        from storage.file_store import list_files
        records = list_files(workspace_id, logical_type=logical_type)
        files = [{
            "file_id": record.get("file_id", ""),
            "logical_type": record.get("logical_type", ""),
            "file_kind": record.get("file_kind", ""),
            "original_name": record.get("original_name", ""),
            "size_bytes": record.get("size_bytes", 0),
            "created_at": record.get("created_at", ""),
            "source": record.get("source", ""),
            "sensitivity": record.get("sensitivity", "internal"),
            "metadata": record.get("metadata", {}),
        } for record in records]
        return jsonify({"ok": True, "files": files, "count": len(files)})

    @app.route("/api/storage/events")
    def api_storage_events():
        try:
            workspace_id = validate_workspace_id(request.args.get("workspace_id", ""))
        except ValueError:
            return jsonify({"ok": False, "error": "invalid_workspace_id"}), 400

        def generate():
            import queue
            from storage.events import subscribe
            with subscribe(workspace_id) as subscriber:
                yield "event: connected\ndata: {}\n\n"
                while True:
                    try:
                        yield f"event: storage_changed\ndata: {subscriber.get(timeout=25)}\n\n"
                    except queue.Empty:
                        yield ": keepalive\n\n"

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
