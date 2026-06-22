# agent/modules/cmdb/service.py
"""CMDB device asset management — persistent JSONL storage."""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path


def _db_dir(workspace_id: str) -> Path:
    from storage.paths import workspace_root
    d = workspace_root(workspace_id) / "cmdb"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_asset(workspace_id: str, asset: dict) -> dict:
    """Create or update a device asset."""
    record = {
        "asset_id": asset.get("asset_id", str(uuid.uuid4())[:12]),
        "name": asset.get("name", ""),
        "type": asset.get("type", "switch"),  # switch/router/firewall/server
        "vendor": asset.get("vendor", ""),
        "model": asset.get("model", ""),
        "host": asset.get("host", ""),
        "port": int(asset.get("port", 22)),
        "protocol": asset.get("protocol", "ssh"),
        "username": asset.get("username", ""),
        "password": _obfuscate(asset.get("password", "")),
        "location": asset.get("location", ""),
        "description": asset.get("description", ""),
        "tags": asset.get("tags", []),
        "created_at": asset.get("created_at", _now()),
        "updated_at": _now(),
    }
    path = _db_dir(workspace_id) / "assets.jsonl"
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return {"ok": True, "asset_id": record["asset_id"]}


def list_assets(workspace_id: str) -> list[dict]:
    """List all non-deleted assets."""
    path = _db_dir(workspace_id) / "assets.jsonl"
    if not path.exists():
        return []
    assets = {}
    deleted = set()
    for line in path.read_text(encoding="utf-8").strip().split("\n"):
        if not line.strip():
            continue
        try:
            d = json.loads(line)
            aid = d.get("asset_id", "")
            if not aid:
                continue
            if d.get("deleted"):
                deleted.add(aid)
                continue
            if aid not in deleted:
                d.pop("password", None)  # never expose
                assets[aid] = d
        except json.JSONDecodeError:
            continue
    return list(assets.values())


def get_asset(workspace_id: str, asset_id: str) -> dict | None:
    """Get single asset by ID (includes password for internal use)."""
    path = _db_dir(workspace_id) / "assets.jsonl"
    if not path.exists():
        return None
    for line in reversed(path.read_text(encoding="utf-8").strip().split("\n")):
        if not line.strip():
            continue
        try:
            d = json.loads(line)
            if d.get("asset_id") == asset_id:
                if d.get("deleted"):
                    return None
                return d
        except json.JSONDecodeError:
            continue
    return None


def delete_asset(workspace_id: str, asset_id: str) -> dict:
    """Soft-delete an asset."""
    path = _db_dir(workspace_id) / "assets.jsonl"
    record = {"asset_id": asset_id, "deleted": True, "deleted_at": _now()}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return {"ok": True}


def _obfuscate(s: str) -> str:
    import base64
    return base64.b64encode(s.encode()).decode()


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")
