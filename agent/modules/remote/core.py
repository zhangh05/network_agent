# agent/modules/remote/core.py
"""SSH/Telnet device connectors with vendor-aware prompt detection."""

from __future__ import annotations

import logging
import re
import select
import socket
import time
from threading import Lock

from agent.modules.remote.vendors import VendorProfile, get_profile

_log = logging.getLogger("remote.core")

READ_TIMEOUT = 10.0
CONNECT_TIMEOUT = 8.0
MAX_SESSION_LOG_LINES = 1000
PAGE_WAIT = 0.3

import threading as _threading
_SESSIONS: dict[str, "DeviceSession"] = {}
_SESSIONS_LOCK = _threading.Lock()


class DeviceSession:
    """Active device connection session."""

    def __init__(self, session_id: str, protocol: str, host: str, port: int,
                 vendor_profile: VendorProfile):
        self.session_id = session_id
        self.protocol = protocol
        self.host = host
        self.port = port
        self.vendor = vendor_profile
        self.connected = False
        self._chan = None
        self._lock = Lock()
        self.log: list[str] = []
        self._buf = b""

    def close(self):
        with self._lock:
            if self._chan:
                try: self._chan.close()
                except Exception: pass
                self._chan = None
            self.connected = False

    def send(self, data: bytes):
        with self._lock:
            if self._chan:
                try:
                    if hasattr(self._chan, "sendall"):
                        self._chan.sendall(data)
                    elif hasattr(self._chan, "send"):
                        self._chan.send(data)
                    elif hasattr(self._chan, "write"):
                        self._chan.write(data)
                except Exception:
                    pass

    def recv(self, timeout: float = 0.5) -> bytes:
        """Read available data. Returns b'' if nothing ready."""
        with self._lock:
            if isinstance(self._chan, _TelnetSocket):
                return self._chan.recv(4096)

            # paramiko channel
            if hasattr(self._chan, "recv_ready"):
                try:
                    if not self._chan.recv_ready():
                        return b""
                    return self._chan.recv(4096)
                except Exception:
                    return b""
            return b""


# ═══════════════════════════════════════════════════════════════════════
# Connection functions
# ═══════════════════════════════════════════════════════════════════════

def ssh_connect(session_id: str, host: str, port: int,
                username: str, password: str,
                vendor: str = "generic") -> DeviceSession:
    import paramiko
    profile = get_profile(vendor)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        client.connect(hostname=host, port=port, username=username, password=password,
                       timeout=CONNECT_TIMEOUT, look_for_keys=False, allow_agent=False)
    except paramiko.AuthenticationException:
        client.close()
        raise ConnectionError(f"SSH 认证失败: {username}@{host}:{port}")
    except Exception as e:
        client.close()
        raise ConnectionError(f"SSH 连接失败: {e}")

    try:
        chan = client.invoke_shell(term="xterm", width=160, height=40)
        chan.settimeout(1.0)
    except Exception as e:
        client.close()
        raise ConnectionError(f"SSH shell 失败: {e}")

    session = DeviceSession(session_id, "ssh", host, port, profile)
    session._chan = chan
    session.connected = True
    with _SESSIONS_LOCK:
        _SESSIONS[session_id] = session

    time.sleep(0.5)
    banner = _read_until_prompt(session)
    session.log.append(banner.decode("utf-8", errors="replace"))
    for cmd in profile.init_commands:
        _exec_and_wait(session, cmd)
    return session


def telnet_connect(session_id: str, host: str, port: int,
                   username: str = "", password: str = "",
                   vendor: str = "generic") -> DeviceSession:
    """Connect via raw socket — transparent TCP bridge."""
    profile = get_profile(vendor)
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(CONNECT_TIMEOUT)
    try:
        s.connect((host, port))
        s.settimeout(READ_TIMEOUT)
    except Exception as e:
        s.close()
        raise ConnectionError(f"Telnet 连接失败 {host}:{port}: {e}")

    tn = _TelnetSocket(s)
    session = DeviceSession(session_id, "telnet", host, port, profile)
    session._chan = tn
    session.connected = True
    with _SESSIONS_LOCK:
        _SESSIONS[session_id] = session
    # Wake console server
    tn.sendall(b"\r\n")
    return session


def exec_command(session_id: str, command: str) -> dict:
    session = _SESSIONS.get(session_id)
    if not session or not session.connected:
        return {"ok": False, "error": "session_not_connected"}
    try:
        output = _exec_and_wait(session, command)
        return {"ok": True, "output": output, "session_id": session_id}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def send_interactive(session_id: str, data: str) -> dict:
    session = _SESSIONS.get(session_id)
    if not session or not session.connected:
        return {"ok": False, "error": "session_not_connected"}
    try:
        session.send(data.encode("utf-8"))
        time.sleep(0.05)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def disconnect(session_id: str) -> dict:
    with _SESSIONS_LOCK:
        session = _SESSIONS.pop(session_id, None)
    if session:
        session.close()
    return {"ok": True}


def get_session(session_id: str) -> DeviceSession | None:
    with _SESSIONS_LOCK:
        return _SESSIONS.get(session_id)


def list_sessions() -> list[dict]:
    return [{
        "session_id": s.session_id, "protocol": s.protocol,
        "host": s.host, "port": s.port, "vendor": s.vendor.vendor,
        "connected": s.connected,
    } for s in _SESSIONS.values()]


# ═══════════════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════════════

def _read_until_prompt(session: DeviceSession) -> bytes:
    buf = b""
    deadline = time.time() + READ_TIMEOUT
    profile = session.vendor
    while time.time() < deadline:
        chunk = session.recv(timeout=0.3)
        if chunk:
            buf += chunk
            decoded = buf.decode("utf-8", errors="replace")
            if profile.match_paging(decoded):
                session.send(profile.paging_response.encode())
                time.sleep(PAGE_WAIT)
                continue
            if profile.match_prompt(decoded):
                return buf
            deadline = time.time() + READ_TIMEOUT
        else:
            time.sleep(0.05)
    return buf


def _exec_and_wait(session: DeviceSession, command: str) -> str:
    session.send((command + "\n").encode())
    time.sleep(0.2)
    output = _read_until_prompt(session)
    text = output.decode("utf-8", errors="replace")
    if len(session.log) < MAX_SESSION_LOG_LINES:
        session.log.append(text)
    else:
        session.log[-1] = text  # rotate last entry
    return text


# ═══════════════════════════════════════════════════════════════════════
# Telnet socket wrapper
# ═══════════════════════════════════════════════════════════════════════

class _TelnetSocket:
    """Raw socket + Telnet IAC negotiation filter."""

    def __init__(self, sock):
        self.sock = sock

    def close(self):
        try: self.sock.close()
        except Exception: pass

    def sendall(self, data: bytes):
        self.sock.sendall(data)

    def recv(self, n: int = 4096) -> bytes:
        """Non-blocking recv with IAC filtering."""
        try:
            ready = select.select([self.sock], [], [], 0.05)
            if not ready[0]:
                return b""
            data = self.sock.recv(n)
            if data:
                return self._filter_iac(data)
        except Exception:
            pass
        return b""

    def _filter_iac(self, data: bytes) -> bytes:
        result = bytearray()
        i = 0
        while i < len(data):
            if data[i] == 255 and i + 1 < len(data):
                cmd = data[i + 1]
                if cmd in (251, 252, 253, 254) and i + 2 < len(data):
                    # WILL/WONT/DO/DONT -> reply WONT/DONT
                    self.sock.sendall(bytes([255, 254 if cmd in (251, 252) else 252, data[i + 2]]))
                    i += 3
                elif cmd in (251, 252, 253, 254):
                    # Truncated IAC — skip
                    i = len(data)
                elif cmd == 250:
                    end = data.find(bytes([255, 240]), i + 2)
                    i = end + 2 if end > 0 else i + 2
                else:
                    i += 2
            else:
                result.append(data[i])
                i += 1
        return bytes(result)
