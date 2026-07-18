"""Remote terminal metadata and saved-device API.

Interactive connection management and terminal I/O live exclusively on
``/ws/remote/terminal``.
"""

from flask import request, jsonify
from workspace.ids import validate_workspace_id

from agent.modules.remote.service import (
    save_device, list_devices, delete_device, get_vendors,
)

def _invalid_ws():
    return jsonify({"ok": False, "error": "invalid_workspace_id"}), 400


def _validated_ws_id(raw=""):
    try:
        return validate_workspace_id(raw), None
    except ValueError:
        return None, _invalid_ws()


def register_remote_routes(app):
    """Register REST routes used by the remote-terminal frontend."""

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
