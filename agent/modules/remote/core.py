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
PRE_COMMAND_DRAIN_QUIET = 0.08
PRE_COMMAND_DRAIN_MAX = 0.45
SESSION_IDLE_TTL = 1800.0  # 30 min — disconnect idle sessions to free memory

import threading as _threading
_SESSIONS: dict[str, "DeviceSession"] = {}
_SESSIONS_LOCK = _threading.Lock()
_LAST_CLEANUP = 0.0


class DeviceSession:
    """Active device connection session."""

    def __init__(self, session_id: str, protocol: str, host: str, port: int,
                 vendor_profile: VendorProfile, workspace_id: str = ""):
        self.session_id = session_id
        self.workspace_id = str(workspace_id or "")
        self.protocol = protocol
        self.host = host
        self.port = port
        self.vendor = vendor_profile
        self.connected = False
        self._chan = None
        self._lock = Lock()
        self.log: list[str] = []
        self._buf = b""
        self.command_timeout: float = 0.0  # 0 = use READ_TIMEOUT only

    def close(self):
        with self._lock:
            if self._chan:
                try: self._chan.close()
                except Exception: _log.debug("remote: chan close during shutdown", exc_info=True)
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
                    _log.debug("remote: send to device channel failed",
                               exc_info=True)
                    self.connected = False
                    self._chan = None

    def resize(self, cols: int, rows: int) -> None:
        cols = max(20, min(int(cols or 160), 240))
        rows = max(8, min(int(rows or 40), 80))
        with self._lock:
            chan = self._chan
            if not chan:
                return
            try:
                if hasattr(chan, "resize_pty"):
                    chan.resize_pty(width=cols, height=rows)
                elif hasattr(chan, "set_pty_size"):
                    chan.set_pty_size(cols, rows)
            except Exception:
                _log.debug("remote: resize device pty failed", exc_info=True)

    def recv(self, timeout: int = 0) -> bytes:
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
                    _log.debug("remote: paramiko recv_ready / recv failed",
                               exc_info=True)
                    return b""
            return b""


# ═══════════════════════════════════════════════════════════════════════
# Connection functions
# ═══════════════════════════════════════════════════════════════════════

def _cleanup_idle_sessions(ttl: float = SESSION_IDLE_TTL) -> int:
    """Disconnect sessions idle for > *ttl* seconds. Returns count of cleaned sessions."""
    global _LAST_CLEANUP
    now = time.time()
    if now - _LAST_CLEANUP < 60:  # don't scan more than once per minute
        return 0
    _LAST_CLEANUP = now
    removed = 0
    with _SESSIONS_LOCK:
        for sid in list(_SESSIONS):
            sess = _SESSIONS.get(sid)
            if sess is None:
                continue
            # Sessions without a connected channel or with no activity for ttl
            if not sess.connected:
                _SESSIONS.pop(sid, None)
                removed += 1
            elif not hasattr(sess, "_last_active"):
                sess._last_active = now  # initialise timestamp
    return removed


def ssh_connect(session_id: str, host: str, port: int,
                username: str, password: str,
                vendor: str = "generic",
                terminal_cols: int = 160,
                terminal_rows: int = 40,
                workspace_id: str = "") -> DeviceSession:
    import paramiko
    _cleanup_idle_sessions()
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
        chan = client.invoke_shell(
            term="xterm",
            width=max(20, min(int(terminal_cols or 160), 240)),
            height=max(8, min(int(terminal_rows or 40), 80)),
        )
        chan.settimeout(1.0)
    except Exception as e:
        client.close()
        raise ConnectionError(f"SSH shell 失败: {e}")

    session = DeviceSession(session_id, "ssh", host, port, profile, workspace_id=workspace_id)
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
                   vendor: str = "generic",
                   workspace_id: str = "") -> DeviceSession:
    """Connect via Telnet.

    Telnet credentials are optional. Some console servers expose a
    ready prompt immediately, while others ask for username/password.
    We only answer login prompts when the caller provided the matching
    credential; otherwise the socket stays connected for manual input.
    """
    _cleanup_idle_sessions()
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
    session = DeviceSession(session_id, "telnet", host, port, profile, workspace_id=workspace_id)
    session._chan = tn
    session.connected = True
    with _SESSIONS_LOCK:
        _SESSIONS[session_id] = session
    # Wake console server
    tn.sendall(b"\r\n")
    _telnet_maybe_login(session, username=username, password=password)
    return session


def exec_command(session_id: str, command: str, *, timeout: float = 0.0) -> dict:
    session = _SESSIONS.get(session_id)
    if not session or not session.connected:
        return {"ok": False, "error": "session_not_connected"}
    try:
        if timeout > 0:
            session.command_timeout = timeout
        output = _exec_and_wait(session, command)
        # Post-send check: if the channel died during send(), _exec_and_wait
        # returns empty; connected flag is now False.
        if not output and not session.connected:
            return {"ok": False, "error": "session_lost_during_execution", "output": output, "session_id": session_id}
        return {"ok": True, "output": output, "session_id": session_id}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}
    finally:
        if timeout > 0:
            session.command_timeout = 0.0


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


def resize_session(session_id: str, cols: int, rows: int) -> dict:
    session = _SESSIONS.get(session_id)
    if not session or not session.connected:
        return {"ok": False, "error": "session_not_connected"}
    session.resize(cols, rows)
    return {"ok": True}


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
        "connected": s.connected, "workspace_id": s.workspace_id,
    } for s in _SESSIONS.values()]


# ═══════════════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════════════

def _read_until_prompt(session: DeviceSession) -> bytes:
    buf = b""
    started = time.time()
    deadline = time.time() + READ_TIMEOUT
    # Absolute command timeout overrides the resetting idle deadline
    abs_deadline = started + session.command_timeout if session.command_timeout > 0 else 0.0
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
            # Reset idle deadline (data is flowing)
            deadline = time.time() + READ_TIMEOUT
            # But respect absolute timeout if set
            if abs_deadline > 0 and time.time() >= abs_deadline:
                return buf
        else:
            time.sleep(0.05)
        # Absolute timeout check on every loop iteration
        if abs_deadline > 0 and time.time() >= abs_deadline:
            return buf
    return buf


def _drain_available(session: DeviceSession, *,
                     quiet_window: float = PRE_COMMAND_DRAIN_QUIET,
                     max_wait: float = PRE_COMMAND_DRAIN_MAX) -> bytes:
    """Clear stale channel output before sending the next command.

    Interactive SSH/Telnet channels can leave a prompt or delayed output
    in the receive buffer after login, paging, or a slow command. If we
    send the next command before draining it, ``_read_until_prompt`` may
    return against that stale prompt and shift command outputs by one
    step. The drained bytes are intentionally not returned to callers as
    command output.
    """
    drained = b""
    deadline = time.time() + max_wait
    quiet_deadline = time.time() + quiet_window
    while time.time() < deadline:
        chunk = session.recv(timeout=0.05)
        if chunk:
            drained += chunk
            quiet_deadline = time.time() + quiet_window
            continue
        if time.time() >= quiet_deadline:
            break
        time.sleep(0.02)
    if drained and len(session.log) < MAX_SESSION_LOG_LINES:
        session.log.append(drained.decode("utf-8", errors="replace"))
    return drained


def _exec_and_wait(session: DeviceSession, command: str) -> str:
    _drain_available(session)
    session.send((command + "\n").encode())
    time.sleep(0.2)
    output = _read_until_prompt(session)
    text = output.decode("utf-8", errors="replace")
    if len(session.log) < MAX_SESSION_LOG_LINES:
        session.log.append(text)
    else:
        session.log[-1] = text  # rotate last entry
    return text


def _telnet_maybe_login(session: DeviceSession, *, username: str = "", password: str = "") -> None:
    """Best-effort Telnet login prompt handling.

    This is intentionally conservative: no credentials means no
    automatic input. The terminal remains interactive, so operators can
    type credentials manually for devices with unusual prompts.
    """
    username = str(username or "")
    password = str(password or "")
    saw_username = False
    saw_password = False
    buf = b""
    deadline = time.time() + 1.5

    while time.time() < deadline:
        chunk = session.recv(timeout=0.2)
        if chunk:
            buf += chunk
            text = buf.decode("utf-8", errors="replace")
            lowered = text.lower()

            if not saw_username and _looks_like_telnet_username_prompt(lowered):
                saw_username = True
                if username:
                    session.send((username + "\r\n").encode("utf-8"))
                    deadline = time.time() + 1.5
                    continue
                break

            if not saw_password and _looks_like_telnet_password_prompt(lowered):
                saw_password = True
                if password:
                    session.send((password + "\r\n").encode("utf-8"))
                    deadline = time.time() + 1.5
                    continue
                break

            if session.vendor.match_prompt(text):
                break
            deadline = time.time() + 0.4
        else:
            time.sleep(0.05)

    if buf:
        text = buf.decode("utf-8", errors="replace")
        if len(session.log) < MAX_SESSION_LOG_LINES:
            session.log.append(text)


def _looks_like_telnet_username_prompt(text: str) -> bool:
    return bool(re.search(r"(username|login|user name|用户名|登录名)\s*[:：]?\s*$", text, re.I))


def _looks_like_telnet_password_prompt(text: str) -> bool:
    return bool(re.search(r"(password|passcode|密码|口令)\s*[:：]?\s*$", text, re.I))


# ═══════════════════════════════════════════════════════════════════════
# Telnet socket wrapper
# ═══════════════════════════════════════════════════════════════════════

class _TelnetSocket:
    """Raw socket + Telnet IAC negotiation filter."""

    def __init__(self, sock):
        self.sock = sock

    def close(self):
        try: self.sock.close()
        except Exception: _log.debug("remote: telnet sock close failed", exc_info=True)

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
            _log.debug("remote: telnet recv failed", exc_info=True)
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
