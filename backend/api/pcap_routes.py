"""PCAP analysis API — upload, parse, filter, TCP seq alignment."""

from flask import jsonify, request

from agent.modules.pcap.service import (
    align_pcap_tcp,
    filter_pcap_session,
    get_pcap_session,
    parse_pcap_file,
)
from workspace.ids import validate_workspace_id


def register_pcap_routes(app):
    """Register PCAP analysis API routes."""

    @app.route("/api/pcap/parse", methods=["POST"])
    def api_pcap_parse():
        try:
            ws_id = validate_workspace_id(request.form.get("workspace_id", "default") or "default")
        except ValueError:
            return jsonify({"ok": False, "error": "invalid_workspace_id"}), 400

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
        try:
            ws_id = validate_workspace_id(data.get("workspace_id", "default") or "default")
        except ValueError:
            return jsonify({"ok": False, "error": "invalid_workspace_id"}), 400
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
        ws_id = request.args.get("workspace_id", "default") or "default"
        result = get_pcap_session(session_id, workspace_id=ws_id)
        if not result.get("ok"):
            return jsonify({"ok": False, "error": "session not found"}), 404
        return jsonify(result)

    @app.route("/api/pcap/filter", methods=["POST"])
    def api_pcap_filter():
        try:
            data = request.get_json(silent=True) or {}
        except Exception:
            return jsonify({"ok": False, "error": "invalid_json"}), 400
        result = filter_pcap_session(
            data.get("session_id", ""),
            src=data.get("src", ""),
            sport=data.get("sport", 0),
            dst=data.get("dst", ""),
            dport=data.get("dport", 0),
            workspace_id=data.get("workspace_id", "default") or "default",
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
        result = align_pcap_tcp(
            data.get("session_id", ""),
            src=data.get("src", ""),
            sport=data.get("sport", 0),
            dst=data.get("dst", ""),
            dport=data.get("dport", 0),
            use_filter=all(k in data for k in ("src", "sport", "dst", "dport")),
            workspace_id=data.get("workspace_id", "default") or "default",
        )
        if not result.get("ok"):
            return jsonify({"ok": False, "error": "session not found"}), 404
        return jsonify(result)
