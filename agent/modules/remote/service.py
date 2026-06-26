# agent/modules/remote/service.py
"""Remote device service — connection management, persistence, logging."""

from __future__ import annotations

import json
import time
from pathlib import Path

from agent.modules.remote.core import (
    ssh_connect, telnet_connect, exec_command, send_interactive,
    disconnect, list_sessions, get_session,
)
from agent.modules.remote.vendors import list_vendors, get_profile


def connect_device(workspace_id: str, host: str, port: int, protocol: str,
                   username: str, password: str, vendor: str = "",
                   device_name: str = "") -> dict:
    """Connect to a network device.

    Returns: {ok, session_id, host, banner_snippet}
    """
    sid = f"dev_{int(time.time() * 1000)}_{host.replace('.', '_')}"

    try:
        if protocol == "ssh":
            session = ssh_connect(sid, host, port, username, password, vendor)
        elif protocol == "telnet":
            session = telnet_connect(sid, host, port, username, password, vendor)
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


def run_command(session_id: str, command: str) -> dict:
    """Execute a command on a connected device."""
    return exec_command(session_id, command)


def interactive_input(session_id: str, data: str) -> dict:
    """Send interactive input to a session."""
    return send_interactive(session_id, data)


def close_session(session_id: str, workspace_id: str = "") -> dict:
    """Disconnect and optionally save log."""
    session = get_session(session_id)
    if session and session.log and workspace_id:
        _save_session_log(workspace_id, session_id, session.log)
    return disconnect(session_id)


def get_active_sessions() -> list[dict]:
    return list_sessions()


def get_vendors() -> list[dict]:
    return list_vendors()


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
        "created_at": device.get("created_at", time.strftime("%Y-%m-%dT%H:%M:%S")),
    }
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
                devices.append(d)
        except json.JSONDecodeError:
            continue
    return list(reversed(devices))


def delete_device(workspace_id: str, device_id: str) -> dict:
    """Delete a saved device (tombstone)."""
    path = _remote_dir(workspace_id) / "connections.jsonl"
    if not path.exists():
        return {"ok": False, "error": "not_found"}
    record = {"device_id": device_id, "deleted": True,
              "deleted_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
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
                return _deobfuscate(d.get("password", ""))
        except json.JSONDecodeError:
            continue
    return ""


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
