# agent/modules/remote/core.py
"""SSH/Telnet device connectors with vendor-aware prompt detection.

SSH: paramiko
Telnet: telnetlib (stdlib)
"""

from __future__ import annotations

import logging
import re
import socket
import time
from threading import Lock
from typing import Optional

from agent.modules.remote.vendors import VendorProfile, get_profile

_log = logging.getLogger("remote.core")

# Session timeout (seconds) for read operations
READ_TIMEOUT = 10.0
CONNECT_TIMEOUT = 8.0
PAGE_WAIT = 0.3  # wait after sending space for next page


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
        self._chan = None      # paramiko Channel or telnetlib Telnet
        self._lock = Lock()
        self.log: list[str] = []

    def close(self):
        with self._lock:
            if self._chan:
                try:
                    self._chan.close()
                except Exception:
                    pass
                self._chan = None
            self.connected = False

    def send(self, data: bytes):
        with self._lock:
            if self._chan:
                try:
                    if hasattr(self._chan, "send"):
                        self._chan.send(data)
                    elif hasattr(self._chan, "write"):
                        self._chan.write(data)
                    else:
                        self._chan.sendall(data)
                except Exception:
                    pass

    def read_until(self, pattern: bytes, timeout: float = None) -> bytes:
        """Read until pattern matches or timeout."""
        timeout = timeout or READ_TIMEOUT
        compiled = re.compile(pattern)
        chan = self._chan

        with self._lock:
            # _TelnetSocket has its own read_until
            if isinstance(chan, _TelnetSocket):
                result = chan.read_until([pattern], timeout=timeout)
                return result

            buf = b""
            deadline = time.time() + timeout
            while time.time() < deadline:
                try:
                    if hasattr(chan, "recv"):
                        ready = chan.recv_ready()
                        if not ready:
                            time.sleep(0.05)
                            continue
                        chunk = chan.recv(4096)
                    elif hasattr(chan, "read_very_eager"):
                        chunk = chan.read_very_eager()
                        if not chunk:
                            time.sleep(0.05)
                            continue
                    else:
                        time.sleep(0.05)
                        continue
                except Exception:
                    time.sleep(0.05)
                    continue
                if not chunk:
                    time.sleep(0.05)
                    continue
                buf += chunk
                if compiled.search(buf):
                    return buf
            return buf

    def read_all(self, timeout: float = None) -> bytes:
        """Read all available data until silence."""
        timeout = timeout or 2.0
        chan = self._chan

        with self._lock:
            # _TelnetSocket has its own read_all
            if isinstance(chan, _TelnetSocket):
                return chan.read_all(timeout=timeout)

            buf = b""
            deadline = time.time() + timeout
            while time.time() < deadline:
                try:
                    if hasattr(chan, "recv"):
                        ready = chan.recv_ready()
                        if not ready:
                            time.sleep(0.05)
                            continue
                        chunk = chan.recv(4096)
                    elif hasattr(chan, "read_very_eager"):
                        chunk = chan.read_very_eager()
                    else:
                        break
                except Exception:
                    break
                if chunk:
                    buf += chunk
                    deadline = time.time() + timeout
                else:
                    time.sleep(0.05)
            return buf


# ═══════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════

_SESSIONS: dict[str, DeviceSession] = {}


def ssh_connect(session_id: str, host: str, port: int,
                username: str, password: str,
                vendor: str = "generic") -> DeviceSession:
    """Connect via SSH using paramiko."""
    import paramiko

    profile = get_profile(vendor)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        client.connect(
            hostname=host, port=port,
            username=username, password=password,
            timeout=CONNECT_TIMEOUT,
            look_for_keys=False,
            allow_agent=False,
        )
    except paramiko.AuthenticationException:
        raise ConnectionError(f"SSH 认证失败: {username}@{host}:{port}")
    except paramiko.SSHException as e:
        raise ConnectionError(f"SSH 连接错误: {e}")
    except Exception as e:
        raise ConnectionError(f"连接失败 {host}:{port}: {e}")

    chan = client.invoke_shell(term="xterm", width=160, height=40)
    chan.settimeout(1.0)

    session = DeviceSession(session_id, "ssh", host, port, profile)
    session._chan = chan
    session.connected = True
    _SESSIONS[session_id] = session

    # Read initial banner
    time.sleep(0.5)
    banner = _read_until_prompt(session)
    session.log.append(banner.decode("utf-8", errors="replace"))

    # Send init commands (disable paging)
    for cmd in profile.init_commands:
        _exec_and_wait(session, cmd)

    return session


def telnet_connect(session_id: str, host: str, port: int,
                   username: str, password: str,
                   vendor: str = "generic") -> DeviceSession:
    """Connect via Telnet using raw socket (telnetlib removed in Python 3.13)."""
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
    _SESSIONS[session_id] = session

    try:
        result = tn.read_until([b"Username:", b"login:", b"Login:"], timeout=CONNECT_TIMEOUT)
        session.log.append(result.decode("utf-8", errors="replace"))
        tn.write(username.encode() + b"\r\n")

        result = tn.read_until([b"Password:", b"password:"], timeout=CONNECT_TIMEOUT)
        session.log.append(result.decode("utf-8", errors="replace"))
        tn.write(password.encode() + b"\r\n")

        time.sleep(1.5)
        banner = tn.read_all(timeout=2)
        session.log.append(banner.decode("utf-8", errors="replace"))
    except Exception as e:
        tn.close()
        raise ConnectionError(f"Telnet 登录失败: {e}")

    session.connected = True

    for cmd in profile.init_commands:
        _exec_and_wait(session, cmd)

    return session


class _TelnetSocket:
    """Lightweight Telnet wrapper (replaces deprecated telnetlib)."""

    def __init__(self, sock):
        self.sock = sock
        self._buf = b""

    def close(self):
        try: self.sock.close()
        except: pass

    def send(self, data: bytes):
        self.sock.sendall(data)

    def write(self, data: bytes):
        self.sock.sendall(data)

    def read_very_eager(self) -> bytes:
        """Compatible with telnetlib.Telnet interface."""
        import select
        buf = self._buf
        self._buf = b""
        try:
            ready = select.select([self.sock], [], [], 0.05)
            if ready[0]:
                chunk = self.sock.recv(65536)
                if chunk:
                    buf += self._filter_iac(chunk)
        except Exception:
            pass
        return buf

    def read_until(self, patterns: list[bytes], timeout: float = None) -> bytes:
        import select
        deadline = time.time() + (timeout or READ_TIMEOUT)
        while time.time() < deadline:
            ready = select.select([self.sock], [], [], 0.5)
            if not ready[0]:
                continue
            try:
                chunk = self.sock.recv(4096)
            except socket.timeout:
                continue
            except Exception:
                break
            if not chunk:
                break
            self._buf += self._filter_iac(chunk)
            for pat in patterns:
                if pat.lower() in self._buf.lower():
                    return self._buf
        return self._buf

    def read_all(self, timeout: float = None) -> bytes:
        import select
        timeout = timeout or 1.0
        deadline = time.time() + timeout
        buf = self._buf
        self._buf = b""
        while time.time() < deadline:
            ready = select.select([self.sock], [], [], 0.3)
            if not ready[0]:
                break
            try:
                chunk = self.sock.recv(65536)
            except socket.timeout:
                break
            except Exception:
                break
            if chunk:
                buf += self._filter_iac(chunk)
                deadline = time.time() + timeout
            else:
                break
        return buf

    def _filter_iac(self, data: bytes) -> bytes:
        """Strip Telnet IAC command sequences."""
        result = bytearray()
        i = 0
        while i < len(data):
            if data[i] == 255 and i + 1 < len(data):
                cmd = data[i + 1]
                if cmd in (251, 252, 253, 254):  # WILL/WONT/DO/DONT
                    self.sock.sendall(bytes([255, 254 if cmd in (251, 252) else 252, data[i + 2]]))
                    i += 3
                elif cmd == 250 and i + 2 < len(data):  # SB
                    end = data.find(bytes([255, 240]), i + 2)
                    i = end + 2 if end > 0 else i + 2
                else:
                    i += 2
            else:
                result.append(data[i])
                i += 1
        return bytes(result)


def exec_command(session_id: str, command: str) -> dict:
    """Execute a command on a connected device and return output."""
    session = _SESSIONS.get(session_id)
    if not session or not session.connected:
        return {"ok": False, "error": "session_not_connected"}
    try:
        output = _exec_and_wait(session, command)
        return {"ok": True, "output": output, "session_id": session_id}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def send_interactive(session_id: str, data: str) -> dict:
    """Send interactive keystroke data to session, return received output."""
    session = _SESSIONS.get(session_id)
    if not session or not session.connected:
        return {"ok": False, "error": "session_not_connected"}
    try:
        session.send(data.encode("utf-8"))
        time.sleep(0.1)
        output = session.read_all(timeout=0.8)
        text = output.decode("utf-8", errors="replace")
        if text:
            session.log.append(text)
        return {"ok": True, "output": text}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


def disconnect(session_id: str) -> dict:
    """Close a device session."""
    session = _SESSIONS.pop(session_id, None)
    if session:
        session.close()
    return {"ok": True}


def get_session(session_id: str) -> DeviceSession | None:
    return _SESSIONS.get(session_id)


def list_sessions() -> list[dict]:
    return [{
        "session_id": s.session_id,
        "protocol": s.protocol,
        "host": s.host,
        "port": s.port,
        "vendor": s.vendor.vendor,
        "connected": s.connected,
    } for s in _SESSIONS.values()]


# ═══════════════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════════════

def _read_until_prompt(session: DeviceSession) -> bytes:
    """Read until a known prompt or paging indicator is detected, handling pagination."""
    buf = b""
    deadline = time.time() + READ_TIMEOUT
    profile = session.vendor

    while time.time() < deadline:
        chunk = b""
        try:
            if hasattr(session._chan, "recv"):
                ready = session._chan.recv_ready()
                if ready:
                    chunk = session._chan.recv(4096)
                else:
                    time.sleep(0.03)
                    continue
            elif hasattr(session._chan, "read_very_eager"):
                chunk = session._chan.read_very_eager()
        except Exception:
            time.sleep(0.05)
            continue

        if not chunk:
            time.sleep(0.05)
            continue
        buf += chunk

        decoded = buf.decode("utf-8", errors="replace")
        # Check paging first
        if profile.match_paging(decoded):
            session.send(profile.paging_response.encode())
            time.sleep(PAGE_WAIT)
            continue
        # Check prompt
        if profile.match_prompt(decoded):
            return buf

        deadline = time.time() + READ_TIMEOUT  # reset on data
    return buf


def _exec_and_wait(session: DeviceSession, command: str) -> str:
    """Send command and wait for full output (handle paging)."""
    session.send((command + "\n").encode())
    time.sleep(0.2)
    output = _read_until_prompt(session)
    text = output.decode("utf-8", errors="replace")
    session.log.append(text)
    return text
