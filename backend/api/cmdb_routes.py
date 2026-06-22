"""CMDB API routes."""

from flask import request, jsonify

from agent.modules.cmdb.service import (
    save_asset, list_assets, get_asset, delete_asset,
)


def register_cmdb_routes(app):
    @app.route("/api/cmdb/assets", methods=["GET"])
    def api_cmdb_list():
        ws_id = request.args.get("workspace_id", "default")
        return jsonify({"ok": True, "assets": list_assets(ws_id)})

    @app.route("/api/cmdb/assets", methods=["POST"])
    def api_cmdb_save():
        data = request.get_json(silent=True) or {}
        ws_id = data.pop("workspace_id", "default")
        result = save_asset(ws_id, data)
        return jsonify(result)

    @app.route("/api/cmdb/assets/<asset_id>", methods=["GET"])
    def api_cmdb_get(asset_id):
        ws_id = request.args.get("workspace_id", "default")
        asset = get_asset(ws_id, asset_id)
        if not asset:
            return jsonify({"ok": False, "error": "not_found"}), 404
        return jsonify({"ok": True, "asset": asset})

    @app.route("/api/cmdb/assets/<asset_id>", methods=["DELETE"])
    def api_cmdb_delete(asset_id):
        ws_id = request.args.get("workspace_id", "default")
        result = delete_asset(ws_id, asset_id)
        return jsonify(result)
