# agent/modules/cmdb/service.py
"""CMDB device asset management — persistent JSONL with filtering, stats, export."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import csv
import io
import threading
import time
import uuid
from pathlib import Path
from agent.runtime.utils import now_iso

_locks: dict[str, threading.RLock] = {}

def _get_cmdb_lock(path: Path) -> threading.RLock:
    key = str(path.resolve())
    if key not in _locks:
        _locks[key] = threading.RLock()
    return _locks[key]


# ── helpers ──

def _db_dir(workspace_id: str) -> Path:
    from storage.paths import workspace_root
    d = workspace_root(workspace_id) / "cmdb"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _now() -> str: return now_iso()


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

    path = _db_dir(workspace_id) / "assets.jsonl"
    _cmdb_lock = _get_cmdb_lock(path)
    with _cmdb_lock:
        # TOCTOU fix: hold lock during conflict detection AND write
        # so two concurrent saves can't both pass the check.
        for existing in _load_all(workspace_id):
            existing_port, _ = _parse_port(existing.get("port", 22))
            if str(existing.get("host", "")).strip() == host and existing_port == port:
                if incoming_asset_id and existing.get("asset_id") == incoming_asset_id:
                    continue  # 编辑自己，不冲突
                return {"ok": False, "error": f"资产冲突：{host}:{port} 已存在 ({existing.get('name', 'unknown')})"}

        existing_asset = get_asset(workspace_id, incoming_asset_id, safe=False) if incoming_asset_id else None

        created_at = (
            str(existing_asset.get("created_at") or "").strip()
            if existing_asset else ""
        ) or str(asset.get("created_at") or _now())

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
            "created_at": created_at,
            "updated_at": _now(),
        }
        raw_password = str(asset.get("password") or "")
        if raw_password:
            record["password_secret"] = _seal_secret(workspace_id, raw_password)
        elif existing_asset and existing_asset.get("password"):
            record["password_secret"] = _seal_secret(workspace_id, str(existing_asset["password"]))

        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return {"ok": True, "asset_id": record["asset_id"], "name": record["name"]}


def list_assets(workspace_id: str, *, filter: dict | None = None, sort_by: str = "name") -> list[dict]:
    """List all non-deleted assets with optional filtering and sorting.

    filter keys: type, vendor, region, location, search
    sort_by: name | type | vendor | region | location | host | updated_at
    """
    all_assets = _load_all(workspace_id)
    filtered = _apply_filter(all_assets, filter or {})
    return _sort_assets(filtered, sort_by)


def search_assets(workspace_id: str, query: str) -> list[dict]:
    """Fuzzy search assets by name, vendor, host, model, region, location, description."""
    q = (query or "").strip().lower()
    if not q:
        return []
    assets = _load_all(workspace_id)
    results = []
    for a in assets:
        score = 0
        haystack = (
            f"{a.get('name','')} {a.get('type','')} {a.get('vendor','')} "
            f"{a.get('host','')} {a.get('model','')} {a.get('region','')} "
            f"{a.get('location','')} {a.get('description','')} {' '.join(a.get('tags', []))}"
        ).lower()
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
    """Get single asset by ID.

    Returns ``None`` when no record exists or the asset was deleted.
    When a stored password cannot be decrypted (corrupted key file,
    workspace migration, ciphertext tampering), the returned dict
    carries ``{"password_corrupted": True}`` so callers (inspection
    runner, frontend asset editor) can surface the issue instead of
    silently using an empty password.
    """
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
                has_secret = bool(d.get("password_secret"))
                password = _record_password(workspace_id, d)
                password_corrupted = (
                    has_secret
                    and not password
                    and _open_secret_strict(workspace_id, d.get("password_secret", "")) == _OPEN_SECRET_FAIL
                )
                d.pop("password_secret", None)
                d.pop("password", None)
                if password_corrupted:
                    d["password_corrupted"] = True
                elif not safe and password:
                    d["password"] = password
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
    """Load all non-deleted assets.

    v3.10: also surface ``password_corrupted`` per asset so the UI
    can flag a corrupted stored password. The check uses
    ``_open_secret_strict`` (which distinguishes a real decrypt
    failure from a missing secret) and runs lazily per asset.

    v3.11: acquires the CMDB lock during read to prevent a
    read-write race where a concurrent ``save_asset`` appends a
    partial or interleaved line to the JSONL file.
    """
    path = _db_dir(workspace_id) / "assets.jsonl"
    if not path.exists():
        return []
    lock = _get_cmdb_lock(path)
    with lock:
        raw = path.read_text(encoding="utf-8")
    assets = {}
    deleted = set()
    for line in raw.strip().split("\n"):
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
                # Save secret before popping — password_corrupted check
                # must happen first, not after d.pop() (P1-1 fix).
                secret = d.get("password_secret")
                d.pop("password", None)
                d.pop("password_secret", None)
                # Surface corrupted-password flag without leaking the
                # secret. We do the open check *only* if a secret
                # existed on the latest revision of the row.
                if secret:
                    if _open_secret_strict(workspace_id, secret) == _OPEN_SECRET_FAIL:
                        d["password_corrupted"] = True
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
    region = str(f.get("region") or "").strip().lower()
    if region:
        result = [a for a in result if region in (a.get("region") or "").lower()]
    location = str(f.get("location") or "").strip().lower()
    if location:
        result = [a for a in result if location in (a.get("location") or "").lower()]
    search = str(f.get("search") or "").strip().lower()
    if search:
        filtered = []
        for a in result:
            haystack = f"{a.get('name','')} {a.get('host','')} {a.get('model','')} {a.get('description','')} {a.get('region','')} {a.get('location','')}".lower()
            if search in haystack:
                filtered.append(a)
        result = filtered
    return result


_SORT_KEYS = {
    "name": "name",
    "type": "type",
    "vendor": "vendor",
    "region": "region",
    "location": "location",
    "host": "host",
    "updated_at": "updated_at",
}

def _sort_assets(assets: list[dict], sort_by: str) -> list[dict]:
    key = _SORT_KEYS.get(sort_by, "name")
    return sorted(assets, key=lambda a: (a.get(key) or "").lower())


def _record_password(workspace_id: str, record: dict) -> str:
    secret = str(record.get("password_secret") or "")
    if secret:
        return _open_secret(workspace_id, secret)
    return ""


def _seal_secret(workspace_id: str, value: str) -> str:
    if not value:
        return ""
    nonce = secrets.token_bytes(16)
    plaintext = value.encode("utf-8")
    stream = _secret_stream(workspace_id, nonce, len(plaintext))
    cipher = bytes(a ^ b for a, b in zip(plaintext, stream))
    body = nonce + cipher
    tag = hmac.new(_auth_key(workspace_id), b"cmdb:v2:" + body, hashlib.sha256).digest()
    return "cmdb:v2:" + base64.urlsafe_b64encode(body + tag).decode("ascii")


def _open_secret(workspace_id: str, sealed: str) -> str:
    """Decrypt the current authenticated ``cmdb:v2:`` blob.

    Returns ``""`` on any failure for read paths that treat
    corrupted credentials as "do not expose/use a password".

    v3.9.15: distinguishes *legitimate* empty (sealed = "") from
    *corrupted* failure. A corrupted ciphertext usually means the
    workspace's `.cmdb_secret_key` was lost (e.g. tarball restore
    without the key file). Returning ``""`` silently in that case
    loses the device password without trace.

    Callers that want the failure path should use
    ``_open_secret_strict`` instead.
    """
    opened = _open_secret_strict(workspace_id, sealed)
    return "" if opened == _OPEN_SECRET_FAIL else opened


# Marker characters sentinel for "we tried to decrypt but authentication
# failed / the ciphertext was tampered with". Distinct from "" which
# legitimately maps to "no password stored".
_OPEN_SECRET_FAIL = "\x00\x00CMDB_DECRYPT_FAIL\x00\x00"


def _open_secret_strict(workspace_id: str, sealed: str) -> str:
    """Like ``_open_secret`` but reports decrypt failures explicitly.

    Returns
      * ``""``  — sealed was empty (no password stored), or the
                    workspace has not encrypted anything yet.
      * ``_OPEN_SECRET_FAIL`` — authentication/decryption failed. The
                                  caller can surface this to the UI as
                                  "stored password corrupted" so the
                                  operator re-enters it instead of
                                  silently losing access.
      * plaintext — successful round-trip.

    v3.10: catch ``UnicodeDecodeError`` explicitly so non-utf8
    ciphertext (a key mismatch produces a non-text byte stream) is
    flagged as a corruption rather than propagated up.
    """
    if not sealed:
        return ""
    try:
        if sealed.startswith("cmdb:v2:"):
            payload = base64.urlsafe_b64decode(sealed.split(":", 2)[2].encode("ascii"))
            if len(payload) < 16 + 32:
                return _OPEN_SECRET_FAIL
            body, tag = payload[:-32], payload[-32:]
            expected = hmac.new(_auth_key(workspace_id), b"cmdb:v2:" + body, hashlib.sha256).digest()
            if not hmac.compare_digest(tag, expected):
                return _OPEN_SECRET_FAIL
            nonce, cipher = body[:16], body[16:]
            stream = _secret_stream(workspace_id, nonce, len(cipher))
            plain_bytes = bytes(a ^ b for a, b in zip(cipher, stream))
            try:
                return plain_bytes.decode("utf-8")
            except UnicodeDecodeError:
                # Wrong key / tampered ciphertext: the byte stream
                # doesn't decode as utf-8. Surface as a corruption
                # so the operator can re-enter the password.
                return _OPEN_SECRET_FAIL
    except Exception:
        return _OPEN_SECRET_FAIL
    return _OPEN_SECRET_FAIL


def _secret_stream(workspace_id: str, nonce: bytes, length: int) -> bytes:
    key = _workspace_secret_key(workspace_id)
    chunks: list[bytes] = []
    counter = 0
    while sum(len(c) for c in chunks) < length:
        chunks.append(hashlib.sha256(key + nonce + counter.to_bytes(4, "big")).digest())
        counter += 1
    return b"".join(chunks)[:length]


def _auth_key(workspace_id: str) -> bytes:
    return hashlib.sha256(b"cmdb-auth-v2:" + _workspace_secret_key(workspace_id)).digest()


def _workspace_secret_key(workspace_id: str) -> bytes:
    path = _db_dir(workspace_id) / ".cmdb_secret_key"
    if not path.exists():
        path.write_text(secrets.token_urlsafe(48), encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    return hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).digest()
