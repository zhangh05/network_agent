# agent/modules/cmdb/tools.py
"""CMDB tool handlers — registered as callable LLM tools."""


def tool_list_assets(workspace_id: str = "", filter: str = "",
                     search: str = "", sort_by: str = "name", **kwargs) -> dict:
    """List device assets with optional filtering and search.

    filter: JSON string, e.g. '{"type":"switch","region":"华东"}'
    search: free-text fuzzy match on name/vendor/host/model/region/location
    sort_by: name | type | vendor | region | location | host | updated_at
    """
    from agent.modules.cmdb.service import list_assets, search_assets, get_stats
    try:
        import json as _json

        # If search query provided, use fuzzy search
        if search.strip():
            assets = search_assets(workspace_id, search)
        else:
            fdict = {}
            if filter.strip():
                try:
                    fdict = _json.loads(filter)
                except _json.JSONDecodeError:
                    return {"ok": False, "error": f"invalid filter JSON: {filter}"}
            assets = list_assets(workspace_id, filter=fdict, sort_by=sort_by)

        summary = []
        for a in assets:
            summary.append({
                "asset_id": a.get("asset_id", ""),
                "name": a.get("name", ""),
                "type": a.get("type", ""),
                "vendor": a.get("vendor", ""),
                "model": a.get("model", ""),
                "host": a.get("host", ""),
                "protocol": a.get("protocol", ""),
                "port": a.get("port", 22),
                "username": a.get("username", ""),
                "region": a.get("region", ""),
                "location": a.get("location", ""),
                "tags": a.get("tags", []),
            })

        stats = get_stats(workspace_id)
        return {
            "ok": True,
            "count": len(summary),
            "total_in_cmdb": stats["total"],
            "by_type": stats["by_type"],
            "by_region": stats["by_region"],
            "assets": summary,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)[:200], "assets": []}


def tool_get_asset(workspace_id: str = "", asset_id: str = "", **kwargs) -> dict:
    """Get full details of a single device asset."""
    from agent.modules.cmdb.service import get_asset
    try:
        if not asset_id.strip():
            return {"ok": False, "error": "asset_id is required"}
        asset = get_asset(workspace_id, asset_id, safe=True)
        if not asset:
            return {"ok": False, "error": f"asset '{asset_id}' not found"}
        return {"ok": True, "asset": {
            "asset_id": asset.get("asset_id", ""),
            "name": asset.get("name", ""),
            "type": asset.get("type", ""),
            "vendor": asset.get("vendor", ""),
            "model": asset.get("model", ""),
            "host": asset.get("host", ""),
            "protocol": asset.get("protocol", ""),
            "port": asset.get("port", 22),
            "username": asset.get("username", ""),
            "region": asset.get("region", ""),
            "location": asset.get("location", ""),
            "description": asset.get("description", ""),
            "tags": asset.get("tags", []),
            "created_at": asset.get("created_at", ""),
            "updated_at": asset.get("updated_at", ""),
        }}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_add_asset(workspace_id: str = "", name: str = "", host: str = "",
                   type: str = "switch", vendor: str = "", protocol: str = "ssh",
                   port: int = 22, username: str = "", password: str = "",
                   model: str = "", region: str = "", location: str = "", description: str = "", **kwargs) -> dict:
    """Add a device asset with validation."""
    from agent.modules.cmdb.service import save_asset
    try:
        if not name.strip():
            return {"ok": False, "error": "name is required"}
        result = save_asset(workspace_id, {
            "name": name.strip(), "host": host.strip(), "type": type,
            "vendor": vendor.strip(), "model": model.strip(),
            "protocol": protocol, "port": port, "username": username,
            "password": password,
            "region": region.strip(),
            "location": location.strip(),
            "description": description.strip(),
        })
        return result
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def tool_delete_asset(workspace_id: str = "", asset_id: str = "", **kwargs) -> dict:
    """Soft-delete a device asset."""
    from agent.modules.cmdb.service import delete_asset
    try:
        if not asset_id.strip():
            return {"ok": False, "error": "asset_id is required"}
        return delete_asset(workspace_id, asset_id)
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}
