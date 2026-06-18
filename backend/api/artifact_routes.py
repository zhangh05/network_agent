# backend/api/artifact_routes.py
"""Artifact API routes — CRUD for artifact store."""

from flask import jsonify, request
from workspace.ids import validate_workspace_id
from artifacts.store import (
    save_artifact, sanitize_record,
    list_artifacts, get_artifact, read_artifact_content,
    delete_artifact, promote_artifact, summarize_artifact_content,
    get_run_artifacts, _get_max_size, _get_ws_root,
)


def _invalid_ws():
    return jsonify({"ok": False, "error": "invalid_workspace_id"}), 400


def _invalid_limit():
    return jsonify({"ok": False, "error": "invalid_limit"}), 400


def _validated_ws_id(raw="default"):
    try:
        return validate_workspace_id(raw or "default"), None
    except ValueError:
        return None, _invalid_ws()


def _validated_limit(default=100, max_value=500):
    from backend.api.params import parse_limit
    try:
        return parse_limit(request.args, default=default, max_value=max_value), None
    except ValueError:
        return None, _invalid_limit()


def register_artifact_routes(app):
    """Register all artifact API routes on the Flask app."""

    @app.route("/api/workspaces/<ws_id>/artifacts")
    def api_workspace_artifacts(ws_id):
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        run_id = request.args.get("run_id")
        art_type = request.args.get("artifact_type")
        scope = request.args.get("scope")
        sens = request.args.get("sensitivity")
        inc_del = request.args.get("include_deleted", "0") == "1"
        lim, err = _validated_limit(default=100, max_value=500)
        if err:
            return err
        return jsonify({"artifacts": list_artifacts(ws_id, run_id=run_id, artifact_type=art_type,
                        scope=scope, sensitivity=sens, include_deleted=inc_del, limit=lim)})

    @app.route("/api/workspaces/<ws_id>/artifacts", methods=["POST"])
    def api_workspace_artifact_create(ws_id):
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        data = request.get_json(silent=True) or {}
        rec = save_artifact(
            workspace_id=ws_id, content=data.get("content", ""),
            artifact_type=data.get("artifact_type", ""),
            title=data.get("title", ""), scope=data.get("scope", "workspace"),
            sensitivity=data.get("sensitivity", ""),
            run_id=data.get("run_id", ""),
        )
        if not rec:
            return jsonify({"ok": False, "error": "artifact creation blocked"}), 400
        return jsonify({"ok": True, "artifact": sanitize_record(rec)})

    @app.route("/api/workspaces/<ws_id>/artifacts/upload", methods=["POST"])
    def api_workspace_artifact_upload(ws_id):
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        import re
        max_size = _get_max_size()

        if request.content_length and request.content_length > max_size + 1_048_576:
            return jsonify({"ok": False, "error": "file_too_large"}), 413

        if "file" not in request.files:
            return jsonify({"ok": False, "error": "no file provided"}), 400
        f = request.files["file"]
        if not f.filename:
            return jsonify({"ok": False, "error": "empty filename"}), 400

        safe = re.sub(r"[^a-zA-Z0-9_.-]", "_", f.filename)[:120]
        upload_dir = _get_ws_root() / ws_id / "files" / "upload"
        upload_dir.mkdir(parents=True, exist_ok=True)
        src_path = upload_dir / safe
        f.save(str(src_path))

        file_size = src_path.stat().st_size
        if file_size > max_size:
            src_path.unlink()
            return jsonify({"ok": False, "error": "file_too_large"}), 413

        try:
            content = src_path.read_text(errors="replace")
        except Exception:
            src_path.unlink()
            return jsonify({"ok": False, "error": "cannot read file"}), 400

        rec = save_artifact(
            workspace_id=ws_id, content=content,
            artifact_type=request.form.get("artifact_type", ""),
            title=request.form.get("title", f.filename),
            scope=request.form.get("scope", "workspace"),
            sensitivity=request.form.get("sensitivity", ""),
            run_id=request.form.get("run_id", ""),
        )
        src_path.unlink()
        if not rec:
            return jsonify({"ok": False, "error": "artifact creation blocked"}), 400
        return jsonify({"ok": True, "artifact": sanitize_record(rec)})

    @app.route("/api/workspaces/<ws_id>/artifacts/batch-delete", methods=["POST"])
    def api_artifact_batch_delete(ws_id):
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        data = request.get_json(silent=True) or {}
        ids = data.get("artifact_ids", [])
        if not ids or not isinstance(ids, list):
            return jsonify({"ok": False, "error": "artifact_ids (list) required"}), 400
        deleted = []
        for aid in ids:
            ok = delete_artifact(ws_id, aid)
            if ok:
                deleted.append(aid)
        return jsonify({"ok": True, "deleted": len(deleted), "total": len(ids)})

    @app.route("/api/workspaces/<ws_id>/artifacts/<artifact_id>")
    def api_workspace_artifact(ws_id, artifact_id):
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        rec = get_artifact(ws_id, artifact_id)
        if not rec:
            return jsonify({"ok": False, "error": "artifact not found"}), 404
        return jsonify({"ok": True, "artifact": sanitize_record(rec)})

    @app.route("/api/workspaces/<ws_id>/artifacts/<artifact_id>/content")
    def api_artifact_content(ws_id, artifact_id):
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        art = get_artifact(ws_id, artifact_id)
        if not art:
            return jsonify({"ok": False, "error": "artifact not found"}), 404
        # Public content reads remain conservative. Sensitive knowledge or
        # design artifacts must be accessed through server-side module tools
        # that can apply purpose-specific gates. Translated config is a
        # user-requested output artifact and remains previewable by the UI.
        allow_sensitive = art.artifact_type in {
            "translated_config",
            "output_config",
            "report",
        }
        content = read_artifact_content(ws_id, artifact_id, allow_sensitive=allow_sensitive)
        if content is None:
            return jsonify({"ok": False, "error": "content not accessible"}), 403
        title = art.title if art else ""
        return jsonify({"ok": True, "content": content, "title": title})

    @app.route("/api/workspaces/<ws_id>/artifacts/<artifact_id>", methods=["DELETE"])
    def api_artifact_delete(ws_id, artifact_id):
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        ok = delete_artifact(ws_id, artifact_id)
        return jsonify({"ok": ok})

    @app.route("/api/workspaces/<ws_id>/artifacts/<artifact_id>/promote", methods=["POST"])
    def api_artifact_promote(ws_id, artifact_id):
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        data = request.get_json(silent=True) or {}
        target = data.get("target_scope", "workspace")
        rec = promote_artifact(ws_id, artifact_id, target)
        if not rec:
            return jsonify({"ok": False, "error": "promotion blocked"}), 400
        return jsonify({"ok": True, "artifact": sanitize_record(rec)})

    @app.route("/api/workspaces/<ws_id>/artifacts/<artifact_id>/summarize")
    def api_artifact_summarize(ws_id, artifact_id):
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        s = summarize_artifact_content(ws_id, artifact_id)
        return jsonify({"ok": True, "summary": s})

    @app.route("/api/workspaces/<ws_id>/runs/<run_id>/artifacts")
    def api_run_artifacts(ws_id, run_id):
        ws_id, err = _validated_ws_id(ws_id)
        if err:
            return err
        return jsonify({"ok": True, **get_run_artifacts(ws_id, run_id)})
