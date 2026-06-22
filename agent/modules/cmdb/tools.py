# agent/modules/cmdb/tools.py
"""CMDB tool handlers — registered as callable LLM tools."""

import json


def tool_list_assets(workspace_id: str = "default", **kwargs) -> dict:
    """List all device assets in the CMDB."""
    from agent.modules.cmdb.service import list_assets
    try:
        assets = list_assets(workspace_id)
        # Strip internal fields for LLM consumption
        summary = []
        for a in assets:
            summary.append({
                "name": a.get("name", ""),
                "type": a.get("type", ""),
                "vendor": a.get("vendor", ""),
                "model": a.get("model", ""),
                "host": a.get("host", ""),
                "protocol": a.get("protocol", ""),
                "port": a.get("port", 22),
                "location": a.get("location", ""),
            })
        return {"ok": True, "count": len(summary), "assets": summary}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200], "assets": []}


def tool_get_asset(workspace_id: str = "default", asset_id: str = "", **kwargs) -> dict:
    """Get a single device asset by ID."""
    from agent.modules.cmdb.service import get_asset
    try:
        asset = get_asset(workspace_id, asset_id)
        if not asset:
            return {"ok": False, "error": "asset_not_found"}
        return {"ok": True, "asset": {
            "name": asset.get("name", ""),
            "type": asset.get("type", ""),
            "vendor": asset.get("vendor", ""),
            "host": asset.get("host", ""),
            "protocol": asset.get("protocol", ""),
            "port": asset.get("port", 22),
        }}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_add_asset(workspace_id: str = "default", name: str = "", host: str = "",
                   type: str = "switch", vendor: str = "", protocol: str = "ssh",
                   port: int = 22, username: str = "", password: str = "", **kwargs) -> dict:
    """Add a device asset to the CMDB."""
    from agent.modules.cmdb.service import save_asset
    try:
        result = save_asset(workspace_id, {
            "name": name, "host": host, "type": type, "vendor": vendor,
            "protocol": protocol, "port": port, "username": username,
            "password": password,
        })
        return result
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}
