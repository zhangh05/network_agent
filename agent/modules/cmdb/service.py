# agent/modules/cmdb/service.py
"""CMDB device asset management — persistent JSONL with filtering, stats, export."""

from __future__ import annotations

import json
import csv
import io
import threading
import time
import uuid
from pathlib import Path

_locks: dict[str, threading.Lock] = {}

def _get_cmdb_lock(path: Path) -> threading.Lock:
    key = str(path.resolve())
    if key not in _locks:
        _locks[key] = threading.Lock()
    return _locks[key]


# ── helpers ──

def _db_dir(workspace_id: str) -> Path:
    from storage.paths import workspace_root
    d = workspace_root(workspace_id) / "cmdb"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


_VALID_TYPES = {"switch", "router", "firewall", "server", "load_balancer", "wireless", "other"}
_VALID_PROTOCOLS = {"ssh", "telnet", "https", "snmp", "netconf", "restconf"}


# ── CRUD ──

def save_asset(workspace_id: str, asset: dict) -> dict:
    """Create or update a device asset with validation."""
    name = str(asset.get("name", "")).strip()
    if not name:
        return {"ok": False, "error": "name is required"}
    device_type = str(asset.get("type", "switch")).strip().lower()
    if device_type not in _VALID_TYPES:
        return {"ok": False, "error": f"invalid type '{device_type}', must be one of {sorted(_VALID_TYPES)}"}
    protocol = str(asset.get("protocol", "ssh")).strip().lower()
    if protocol not in _VALID_PROTOCOLS:
        return {"ok": False, "error": f"invalid protocol '{protocol}', must be one of {sorted(_VALID_PROTOCOLS)}"}

    host = str(asset.get("host", "")).strip()
    port, port_error = _parse_port(asset.get("port", 22))
    if port_error:
        return {"ok": False, "error": port_error}
    if not host:
        return {"ok": False, "error": "host is required"}

    # 冲突检测：IP + 端口一致则拒绝添加
    incoming_asset_id = str(asset.get("asset_id") or "")
    for existing in _load_all(workspace_id):
        existing_port, _ = _parse_port(existing.get("port", 22))
        if str(existing.get("host", "")).strip() == host and existing_port == port:
            if incoming_asset_id and existing.get("asset_id") == incoming_asset_id:
                continue  # 编辑自己，不冲突
            return {"ok": False, "error": f"资产冲突：{host}:{port} 已存在 ({existing.get('name', 'unknown')})"}

    record = {
        "asset_id": str(asset.get("asset_id") or str(uuid.uuid4())[:12]),
        "name": name,
        "type": device_type,
        "vendor": str(asset.get("vendor", "")).strip(),
        "model": str(asset.get("model", "")).strip(),
        "host": str(asset.get("host", "")).strip(),
        "port": port,
        "protocol": protocol,
        "username": str(asset.get("username", "")).strip(),
        "region": str(asset.get("region", "")).strip(),
        "location": str(asset.get("location", "")).strip(),
        "description": str(asset.get("description", "")).strip(),
        "tags": [str(t).strip() for t in (asset.get("tags") or []) if str(t).strip()],
        "created_at": str(asset.get("created_at") or _now()),
        "updated_at": _now(),
    }
    path = _db_dir(workspace_id) / "assets.jsonl"
    _cmdb_lock = _get_cmdb_lock(path)
    with _cmdb_lock:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return {"ok": True, "asset_id": record["asset_id"], "name": record["name"]}


def list_assets(workspace_id: str, *, filter: dict | None = None, sort_by: str = "name") -> list[dict]:
    """List all non-deleted assets with optional filtering and sorting.

    filter keys: type, vendor, search (fuzzy on name/host/description)
    sort_by: name | type | vendor | host | updated_at
    """
    all_assets = _load_all(workspace_id)
    filtered = _apply_filter(all_assets, filter or {})
    return _sort_assets(filtered, sort_by)


def search_assets(workspace_id: str, query: str) -> list[dict]:
    """Fuzzy search assets by name, vendor, host, model, description."""
    q = (query or "").strip().lower()
    if not q:
        return []
    assets = _load_all(workspace_id)
    results = []
    for a in assets:
        score = 0
        haystack = f"{a.get('name','')} {a.get('type','')} {a.get('vendor','')} {a.get('host','')} {a.get('model','')} {a.get('description','')} {' '.join(a.get('tags', []))}".lower()
        if q in haystack:
            score += 10
        if q == a.get("name", "").lower():
            score += 40
        if q in a.get("name", "").lower():
            score += 20
        if q in a.get("host", "").lower():
            score += 15
        if score > 0:
            results.append((score, a))
    results.sort(key=lambda x: -x[0])
    return [r[1] for r in results[:20]]


def get_asset(workspace_id: str, asset_id: str, *, safe: bool = True) -> dict | None:
    """Get single asset by ID."""
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
                if safe:
                    d.pop("password", None)
                return d
        except json.JSONDecodeError:
            continue
    return None


def delete_asset(workspace_id: str, asset_id: str) -> dict:
    """Soft-delete an asset."""
    existing = get_asset(workspace_id, asset_id, safe=False)
    if not existing:
        return {"ok": False, "error": f"asset '{asset_id}' not found"}
    path = _db_dir(workspace_id) / "assets.jsonl"
    record = {"asset_id": asset_id, "deleted": True, "deleted_at": _now()}
    with _get_cmdb_lock(path):
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return {"ok": True, "name": existing.get("name", "")}


def get_stats(workspace_id: str) -> dict:
    """Statistics: count by type, vendor, protocol, region."""
    assets = _load_all(workspace_id)
    by_type = {}
    by_vendor = {}
    by_protocol = {}
    by_region = {}
    for a in assets:
        t = a.get("type", "other")
        by_type[t] = by_type.get(t, 0) + 1
        v = a.get("vendor", "unknown") or "unknown"
        by_vendor[v] = by_vendor.get(v, 0) + 1
        p = a.get("protocol", "ssh")
        by_protocol[p] = by_protocol.get(p, 0) + 1
        r = a.get("region", "") or "未分类"
        by_region[r] = by_region.get(r, 0) + 1
    return {
        "total": len(assets),
        "by_type": by_type,
        "by_vendor": by_vendor,
        "by_protocol": by_protocol,
        "by_region": by_region,
    }


def export_assets(workspace_id: str) -> str:
    """Export all assets as CSV string."""
    assets = _load_all(workspace_id)
    headers = ["name", "type", "vendor", "model", "host", "port", "protocol", "region", "location", "description", "tags", "created_at", "updated_at"]
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=headers, lineterminator="\n")
    writer.writeheader()
    for a in assets:
        row = {h: _csv_safe(str(a.get(h, ""))) for h in headers}
        row["tags"] = _csv_safe(";".join(a.get("tags", [])))
        writer.writerow(row)
    return out.getvalue()


# ── internal ──

def _load_all(workspace_id: str) -> list[dict]:
    """Load all non-deleted assets."""
    path = _db_dir(workspace_id) / "assets.jsonl"
    if not path.exists():
        return []
    assets = {}
    deleted = set()
    for line in path.read_text(encoding="utf-8").strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
            aid = d.get("asset_id", "")
            if not aid:
                continue
            if d.get("deleted"):
                deleted.add(aid)
                assets.pop(aid, None)  # Remove tombstoned asset
                continue
            if aid not in deleted:
                d.pop("password", None)
                assets[aid] = d
        except json.JSONDecodeError:
            continue
    return list(assets.values())


def _parse_port(raw) -> tuple[int | None, str]:
    try:
        port = int(raw if raw not in (None, "") else 22)
    except (TypeError, ValueError):
        return None, "invalid_port"
    if port < 1 or port > 65535:
        return None, "invalid_port"
    return port, ""


def _csv_safe(value: str) -> str:
    return "'" + value if value.startswith(("=", "+", "-", "@")) else value


def _apply_filter(assets: list[dict], f: dict) -> list[dict]:
    if not f:
        return assets
    result = assets
    dev_type = str(f.get("type") or "").strip().lower()
    if dev_type:
        result = [a for a in result if a.get("type") == dev_type]
    vendor = str(f.get("vendor") or "").strip().lower()
    if vendor:
        result = [a for a in result if vendor in (a.get("vendor") or "").lower()]
    search = str(f.get("search") or "").strip().lower()
    if search:
        filtered = []
        for a in result:
            haystack = f"{a.get('name','')} {a.get('host','')} {a.get('model','')} {a.get('description','')} {a.get('region','')} {a.get('location','')}".lower()
            if search in haystack:
                filtered.append(a)
        result = filtered
    return result


_SORT_KEYS = {"name": "name", "type": "type", "vendor": "vendor", "host": "host", "updated_at": "updated_at"}

def _sort_assets(assets: list[dict], sort_by: str) -> list[dict]:
    key = _SORT_KEYS.get(sort_by, "name")
    return sorted(assets, key=lambda a: (a.get(key) or "").lower())


def _obfuscate(s: str) -> str:
    import base64
    return base64.b64encode(str(s).encode()).decode()
