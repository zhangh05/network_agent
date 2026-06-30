"""Remote device API — connection management, device storage, command execution."""

from flask import request, jsonify
from workspace.ids import validate_workspace_id

from agent.modules.remote.service import (
    connect_device, run_command, close_session, get_active_sessions,
    save_device, list_devices, delete_device, get_device_password, get_vendors,
)

def _invalid_ws():
    return jsonify({"ok": False, "error": "invalid_workspace_id"}), 400


def _validated_ws_id(raw=""):
    try:
        return validate_workspace_id(raw), None
    except ValueError:
        return None, _invalid_ws()


def _parse_port(value, default=22):
    try:
        port = int(value if value not in (None, "") else default)
    except (TypeError, ValueError):
        return None, (jsonify({"ok": False, "error": "invalid_port"}), 400)
    if port < 1 or port > 65535:
        return None, (jsonify({"ok": False, "error": "invalid_port"}), 400)
    return port, None


def register_remote_routes(app):
    """Register remote device API routes."""

    @app.route("/api/remote/connect", methods=["POST"])
    def api_remote_connect():
        data = request.get_json(silent=True) or {}
        ws_id, err = _validated_ws_id(data.get("workspace_id", ""))
        if err:
            return err
        port, err = _parse_port(data.get("port", 22), default=22)
        if err:
            return err
        result = connect_device(
            workspace_id=ws_id,
            host=data.get("host", ""),
            port=port,
            protocol=data.get("protocol", "ssh"),
            username=data.get("username", ""),
            password=data.get("password", ""),
            vendor=data.get("vendor", ""),
            asset_id=data.get("asset_id", ""),
            device_id=data.get("device_id", ""),
        )
        return jsonify(result)

    @app.route("/api/remote/exec", methods=["POST"])
    def api_remote_exec():
        data = request.get_json(silent=True) or {}
        ws_id, err = _validated_ws_id(data.get("workspace_id", ""))
        if err:
            return err
        result = run_command(
            session_id=data.get("session_id", ""),
            command=data.get("command", ""),
            workspace_id=ws_id,
        )
        return jsonify(result)

    @app.route("/api/remote/disconnect", methods=["POST"])
    def api_remote_disconnect():
        data = request.get_json(silent=True) or {}
        ws_id, err = _validated_ws_id(data.get("workspace_id", ""))
        if err:
            return err
        result = close_session(
            session_id=data.get("session_id", ""),
            workspace_id=ws_id,
        )
        return jsonify(result)

    @app.route("/api/remote/sessions", methods=["GET"])
    def api_remote_sessions():
        ws_id, err = _validated_ws_id(request.args.get("workspace_id", ""))
        if err:
            return err
        return jsonify({"ok": True, "sessions": get_active_sessions(ws_id)})

    @app.route("/api/remote/vendors", methods=["GET"])
    def api_remote_vendors():
        return jsonify({"ok": True, "vendors": get_vendors()})

    @app.route("/api/remote/devices", methods=["GET"])
    def api_remote_devices():
        ws_id, err = _validated_ws_id(request.args.get("workspace_id", ""))
        if err:
            return err
        return jsonify({"ok": True, "devices": list_devices(ws_id)})

    @app.route("/api/remote/devices", methods=["POST"])
    def api_remote_devices_save():
        data = request.get_json(silent=True) or {}
        ws_id, err = _validated_ws_id(data.pop("workspace_id", ""))
        if err:
            return err
        result = save_device(ws_id, data)
        return jsonify(result)

    @app.route("/api/remote/devices/<device_id>", methods=["DELETE"])
    def api_remote_devices_delete(device_id):
        ws_id, err = _validated_ws_id(request.args.get("workspace_id", ""))
        if err:
            return err
        result = delete_device(ws_id, device_id)
        return jsonify(result)
