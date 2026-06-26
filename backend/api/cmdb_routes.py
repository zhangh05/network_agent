"""CMDB API routes."""

from flask import request, jsonify
from workspace.ids import validate_workspace_id

from agent.modules.cmdb.service import (
    save_asset, list_assets, get_asset, delete_asset,
)

def _invalid_ws():
    return jsonify({"ok": False, "error": "invalid_workspace_id"}), 400


def _validated_ws_id(raw="default"):
    try:
        return validate_workspace_id(raw or "default"), None
    except ValueError:
        return None, _invalid_ws()


def register_cmdb_routes(app):
    @app.route("/api/cmdb/assets", methods=["GET"])
    def api_cmdb_list():
        ws_id, err = _validated_ws_id(request.args.get("workspace_id", "default"))
        if err:
            return err
        return jsonify({"ok": True, "assets": list_assets(ws_id)})

    @app.route("/api/cmdb/assets", methods=["POST"])
    def api_cmdb_save():
        data = request.get_json(silent=True) or {}
        ws_id, err = _validated_ws_id(data.pop("workspace_id", "default"))
        if err:
            return err
        result = save_asset(ws_id, data)
        return jsonify(result), (200 if result.get("ok") else 400)

    @app.route("/api/cmdb/assets/<asset_id>", methods=["GET"])
    def api_cmdb_get(asset_id):
        ws_id, err = _validated_ws_id(request.args.get("workspace_id", "default"))
        if err:
            return err
        asset = get_asset(ws_id, asset_id)
        if not asset:
            return jsonify({"ok": False, "error": "not_found"}), 404
        return jsonify({"ok": True, "asset": asset})

    @app.route("/api/cmdb/assets/<asset_id>", methods=["DELETE"])
    def api_cmdb_delete(asset_id):
        ws_id, err = _validated_ws_id(request.args.get("workspace_id", "default"))
        if err:
            return err
        result = delete_asset(ws_id, asset_id)
        return jsonify(result)
