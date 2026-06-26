"""PCAP analysis API — upload, parse, filter, TCP seq alignment."""

from flask import jsonify, request

from agent.modules.pcap.service import (
    align_pcap_tcp,
    delete_pcap_session,
    filter_pcap_session,
    get_pcap_session,
    list_pcap_sessions,
    parse_pcap_file,
)
from workspace.ids import validate_workspace_id


def _invalid_ws():
    return jsonify({"ok": False, "error": "invalid_workspace_id"}), 400


def _validated_ws_id(raw="default"):
    try:
        return validate_workspace_id(raw), None
    except ValueError:
        return None, _invalid_ws()


def _confirm_required():
    return jsonify({
        "ok": False,
        "error": "confirm_required",
        "message": "Set confirm=true to delete this PCAP session.",
    }), 400


def register_pcap_routes(app):
    """Register PCAP analysis API routes."""

    @app.route("/api/pcap/parse", methods=["POST"])
    def api_pcap_parse():
        ws_id, err = _validated_ws_id(request.form.get("workspace_id", ""))
        if err:
            return err

        if "file" not in request.files:
            return jsonify({"ok": False, "error": "no file"}), 400
        uploaded = request.files["file"]
        if not uploaded.filename:
            return jsonify({"ok": False, "error": "empty filename"}), 400

        try:
            from storage.file_store import import_user_upload

            rec = import_user_upload(
                workspace_id=ws_id,
                file_source=uploaded.stream,
                original_name=uploaded.filename,
                logical_type="pcap_input",
                file_kind="pcap",
                binary=True,
                source="pcap_parse",
            )
        except Exception as exc:
            return jsonify({
                "ok": False,
                "error": "pcap_upload_failed",
                "message": str(exc)[:200],
            }), 400

        result = parse_pcap_file(ws_id, file_id=rec.file_id)
        if not result.get("ok"):
            errors = result.get("errors") or ["pcap_parse_failed"]
            return jsonify({
                "ok": False,
                "error": str(errors[0]),
                "message": result.get("summary", "无法解析 pcap 文件"),
            }), 400

        return jsonify({
            "ok": True,
            "session_id": result.get("session_id", ""),
            "file_id": rec.file_id,
            "filename": result.get("filename", uploaded.filename),
            "total_packets": result.get("total_packets", 0),
            "connections": result.get("connections", []),
            "summary": result.get("summary", ""),
        })

    @app.route("/api/pcap/parse-file", methods=["POST"])
    def api_pcap_parse_file():
        data = request.get_json(force=True) or {}
        ws_id, err = _validated_ws_id(data.get("workspace_id", ""))
        if err:
            return err
        file_id = str(data.get("file_id", "") or "")
        if not file_id:
            return jsonify({"ok": False, "error": "missing_file_id"}), 400

        result = parse_pcap_file(ws_id, file_id=file_id)
        if not result.get("ok"):
            errors = result.get("errors") or ["pcap_parse_failed"]
            return jsonify({
                "ok": False,
                "error": str(errors[0]),
                "message": result.get("summary", "无法解析 pcap 文件"),
            }), 400

        return jsonify({
            "ok": True,
            "session_id": result.get("session_id", ""),
            "file_id": file_id,
            "filename": result.get("filename", ""),
            "total_packets": result.get("total_packets", 0),
            "connections": result.get("connections", []),
            "summary": result.get("summary", ""),
        })

    @app.route("/api/pcap/session/<session_id>", methods=["GET"])
    def api_pcap_session(session_id):
        ws_id, err = _validated_ws_id(request.args.get("workspace_id", ""))
        if err:
            return err
        result = get_pcap_session(session_id, workspace_id=ws_id)
        if not result.get("ok"):
            return jsonify({"ok": False, "error": "session not found"}), 404
        return jsonify(result)

    @app.route("/api/pcap/session/<session_id>", methods=["DELETE"])
    def api_pcap_session_delete(session_id):
        ws_id, err = _validated_ws_id(request.args.get("workspace_id", ""))
        if err:
            return err
        if request.args.get("confirm", "") != "true":
            return _confirm_required()
        result = delete_pcap_session(session_id, workspace_id=ws_id)
        return jsonify(result)

    @app.route("/api/pcap/sessions", methods=["GET"])
    def api_pcap_sessions():
        ws_id, err = _validated_ws_id(request.args.get("workspace_id", ""))
        if err:
            return err
        try:
            limit = int(request.args.get("limit", "20"))
        except ValueError:
            limit = 20
        sessions = list_pcap_sessions(workspace_id=ws_id, limit=limit)
        return jsonify({"ok": True, "sessions": sessions, "count": len(sessions)})

    @app.route("/api/pcap/filter", methods=["POST"])
    def api_pcap_filter():
        try:
            data = request.get_json(silent=True) or {}
        except Exception:
            return jsonify({"ok": False, "error": "invalid_json"}), 400
        ws_id, err = _validated_ws_id(data.get("workspace_id", ""))
        if err:
            return err
        result = filter_pcap_session(
            data.get("session_id", ""),
            src=data.get("src", ""),
            sport=data.get("sport", 0),
            dst=data.get("dst", ""),
            dport=data.get("dport", 0),
            workspace_id=ws_id,
        )
        if not result.get("ok"):
            return jsonify({"ok": False, "error": "session not found"}), 404
        return jsonify(result)

    @app.route("/api/pcap/align", methods=["POST"])
    def api_pcap_align():
        try:
            data = request.get_json(silent=True) or {}
        except Exception:
            return jsonify({"ok": False, "error": "invalid_json"}), 400
        ws_id, err = _validated_ws_id(data.get("workspace_id", ""))
        if err:
            return err
        result = align_pcap_tcp(
            data.get("session_id", ""),
            src=data.get("src", ""),
            sport=data.get("sport", 0),
            dst=data.get("dst", ""),
            dport=data.get("dport", 0),
            use_filter=all(k in data for k in ("src", "sport", "dst", "dport")),
            workspace_id=ws_id,
        )
        if not result.get("ok"):
            return jsonify({"ok": False, "error": "session not found"}), 404
        return jsonify(result)
