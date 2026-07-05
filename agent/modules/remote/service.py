# agent/modules/remote/service.py
"""Remote device service — connection management, persistence, logging."""

from __future__ import annotations

import json
import time
from pathlib import Path

from agent.runtime.utils import now_iso
from agent.modules.remote.core import (
    ssh_connect, telnet_connect, exec_command, send_interactive,
    resize_session, disconnect, list_sessions, get_session,
)
from agent.modules.remote.vendors import list_vendors, get_profile


def connect_device(workspace_id: str, host: str, port: int, protocol: str,
                   username: str, password: str, vendor: str = "",
                   device_name: str = "", asset_id: str = "", device_id: str = "",
                   terminal_cols: int = 160, terminal_rows: int = 40) -> dict:
    """Connect to a network device.

    Returns: {ok, session_id, host, banner_snippet}
    """
    resolved = _resolve_connection_profile(
        workspace_id=workspace_id,
        host=host,
        port=port,
        protocol=protocol,
        username=username,
        password=password,
        vendor=vendor,
        asset_id=asset_id,
        device_id=device_id,
    )
    if not resolved.get("ok"):
        return resolved

    host = resolved["host"]
    port = int(resolved["port"])
    protocol = resolved["protocol"]
    username = resolved["username"]
    password = resolved["password"]
    vendor = resolved["vendor"]

    sid = f"dev_{int(time.time() * 1000)}_{host.replace('.', '_')}"

    try:
        if protocol == "ssh":
            session = ssh_connect(
                sid, host, port, username, password, vendor,
                terminal_cols=terminal_cols,
                terminal_rows=terminal_rows,
                workspace_id=workspace_id,
            )
        elif protocol == "telnet":
            session = telnet_connect(
                sid, host, port, username, password, vendor,
                workspace_id=workspace_id,
            )
        else:
            return {"ok": False, "error": f"unsupported protocol: {protocol}"}

        banner = session.log[0][:200] if session.log else ""

        # Save connection log directory
        _ensure_log_dir(workspace_id)

        return {
            "ok": True,
            "session_id": sid,
            "host": host,
            "vendor": session.vendor.vendor,
            "banner": banner,
        }
    except ConnectionError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        return {"ok": False, "error": f"连接失败: {e}"}


def run_command(session_id: str, command: str, workspace_id: str) -> dict:
    """Execute a command on a connected device."""
    guard = _require_session_workspace(session_id, workspace_id)
    if guard:
        return guard
    return exec_command(session_id, command)


def interactive_input(session_id: str, data: str, workspace_id: str) -> dict:
    """Send interactive input to a session."""
    guard = _require_session_workspace(session_id, workspace_id)
    if guard:
        return guard
    return send_interactive(session_id, data)


def resize_terminal(session_id: str, cols: int, rows: int, workspace_id: str) -> dict:
    """Resize an active remote terminal PTY when supported."""
    guard = _require_session_workspace(session_id, workspace_id)
    if guard:
        return guard
    return resize_session(session_id, cols, rows)


def close_session(session_id: str, workspace_id: str = "") -> dict:
    """Disconnect and optionally save log."""
    guard = _require_session_workspace(session_id, workspace_id)
    if guard:
        return guard
    session = get_session(session_id)
    if session and session.log and workspace_id:
        _save_session_log(workspace_id, session_id, session.log)
    return disconnect(session_id)


def get_active_sessions(workspace_id: str) -> list[dict]:
    return [
        session for session in list_sessions()
        if session.get("workspace_id") == workspace_id
    ]


def get_vendors() -> list[dict]:
    return list_vendors()


def _require_session_workspace(session_id: str, workspace_id: str) -> dict | None:
    """Fail closed for all session follow-up operations."""
    if not session_id:
        return {"ok": False, "error": "session_id is required"}
    if not workspace_id:
        return {"ok": False, "error": "workspace_id is required"}
    session = get_session(session_id)
    if not session or not getattr(session, "connected", False):
        return {"ok": False, "error": "session_not_connected"}
    if getattr(session, "workspace_id", "") != workspace_id:
        return {"ok": False, "error": "session_workspace_mismatch"}
    return None


# ═══════════════════════════════════════════════════════════════════════
# Device connection persistence
# ═══════════════════════════════════════════════════════════════════════

def _remote_dir(workspace_id: str) -> Path:
    from storage.paths import workspace_root
    d = workspace_root(workspace_id) / "remote"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ensure_log_dir(workspace_id: str) -> Path:
    from storage.paths import workspace_root
    d = workspace_root(workspace_id) / "remote" / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_device(workspace_id: str, device: dict) -> dict:
    """Save a device connection profile."""
    record = {
        "device_id": device.get("device_id", f"dev_{int(time.time())}"),
        "name": device.get("name", ""),
        "host": device.get("host", ""),
        "port": device.get("port", 22),
        "protocol": device.get("protocol", "ssh"),
        "vendor": device.get("vendor", ""),
        "username": device.get("username", ""),
        "created_at": device.get("created_at", now_iso()),
    }
    password = str(device.get("password") or "")
    if password:
        from agent.modules.cmdb.service import _seal_secret
        record["password_secret"] = _seal_secret(workspace_id, password)
    path = _remote_dir(workspace_id) / "connections.jsonl"
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return {"ok": True, "device_id": record["device_id"]}


def list_devices(workspace_id: str) -> list[dict]:
    """List saved device connections."""
    path = _remote_dir(workspace_id) / "connections.jsonl"
    if not path.exists():
        return []
    devices = []
    seen = set()
    for line in reversed(path.read_text(encoding="utf-8").strip().split("\n")):
        if not line.strip():
            continue
        try:
            d = json.loads(line)
            did = d.get("device_id", "")
            if did and did not in seen:
                seen.add(did)
                d.pop("password", None)
                d.pop("password_secret", None)
                devices.append(d)
        except json.JSONDecodeError:
            continue
    return list(reversed(devices))


def delete_device(workspace_id: str, device_id: str) -> dict:
    """Physically delete a saved device from JSONL."""
    path = _remote_dir(workspace_id) / "connections.jsonl"
    if not path.exists():
        return {"ok": False, "error": "not_found"}
    lines = path.read_text(encoding="utf-8").strip().split("\n")
    kept = []
    for line in lines:
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            kept.append(line)
            continue
        if rec.get("device_id") == device_id:
            continue
        kept.append(line)
    path.write_text("\n".join(kept) + ("\n" if kept else ""))
    return {"ok": True}


def get_device_password(workspace_id: str, device_id: str) -> str:
    """Retrieve the actual password for a saved device (internal use)."""
    path = _remote_dir(workspace_id) / "connections.jsonl"
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8").strip().split("\n"):
        try:
            d = json.loads(line)
            if d.get("device_id") == device_id:
                return _extract_saved_password(workspace_id, d)
        except json.JSONDecodeError:
            continue
    return ""


def _resolve_connection_profile(
    *,
    workspace_id: str,
    host: str,
    port: int,
    protocol: str,
    username: str,
    password: str,
    vendor: str,
    asset_id: str = "",
    device_id: str = "",
) -> dict:
    if asset_id:
        from agent.modules.cmdb.service import get_asset
        asset = get_asset(workspace_id, asset_id, safe=False)
        if not asset:
            return {"ok": False, "error": f"asset_not_found: {asset_id}"}
        host = str(asset.get("host") or host)
        port = int(asset.get("port") or port or 22)
        protocol = str(asset.get("protocol") or protocol or "ssh")
        username = str(asset.get("username") or username)
        password = str(asset.get("password") or password)
        vendor = str(asset.get("vendor") or vendor)
    elif device_id and not password:
        password = get_device_password(workspace_id, device_id)
    elif not password and host:
        matched = _find_cmdb_asset_for_connection(
            workspace_id=workspace_id,
            host=host,
            port=port,
            username=username,
            protocol=protocol,
        )
        if matched:
            username = str(matched.get("username") or username)
            password = str(matched.get("password") or password)
            vendor = str(matched.get("vendor") or vendor)
            protocol = str(matched.get("protocol") or protocol or "ssh")
            port = int(matched.get("port") or port or 22)

    if not host:
        return {"ok": False, "error": "host is required"}
    if protocol == "ssh" and not username:
        return {"ok": False, "error": "username is required"}
    if protocol == "ssh" and not password:
        return {"ok": False, "error": "password is required"}
    return {
        "ok": True,
        "host": host,
        "port": int(port or (23 if protocol == "telnet" else 22)),
        "protocol": protocol or "ssh",
        "username": username,
        "password": password,
        "vendor": vendor,
    }


def _find_cmdb_asset_for_connection(
    *,
    workspace_id: str,
    host: str,
    port: int,
    username: str,
    protocol: str,
) -> dict | None:
    from agent.modules.cmdb.service import get_asset, list_assets

    matches = []
    for asset in list_assets(workspace_id):
        if str(asset.get("host") or "").strip() != str(host or "").strip():
            continue
        if int(asset.get("port") or port or 22) != int(port or 22):
            continue
        if protocol and str(asset.get("protocol") or "").lower() != str(protocol).lower():
            continue
        if username and str(asset.get("username") or "") != str(username):
            continue
        matches.append(asset)
    if len(matches) != 1:
        return None
    return get_asset(workspace_id, str(matches[0].get("asset_id") or ""), safe=False)


def _extract_saved_password(workspace_id: str, record: dict) -> str:
    secret = str(record.get("password_secret") or "")
    if secret:
        from agent.modules.cmdb.service import _open_secret
        return _open_secret(workspace_id, secret)
    return _deobfuscate(str(record.get("password") or ""))


def _save_session_log(workspace_id: str, session_id: str, log_lines: list[str]):
    try:
        log_dir = _ensure_log_dir(workspace_id)
        path = log_dir / f"{session_id}.log"
        path.write_text("\n".join(log_lines), encoding="utf-8")
    except Exception:
        pass


# Simple obfuscation (not real encryption — user should be warned)
def _obfuscate(s: str) -> str:
    import base64
    return base64.b64encode(s.encode()).decode()


def _deobfuscate(s: str) -> str:
    import base64
    try:
        return base64.b64decode(s).decode()
    except Exception:
        return ""
