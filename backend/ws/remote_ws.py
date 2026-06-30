"""Remote terminal WebSocket — real-time interactive device session.

Uses flask_sock (same pattern as agent_ws.py).
"""

import json
import logging
import threading

from flask import request
from flask_sock import Sock
from backend.core.auth import is_allowed_browser_origin

sock = Sock()
_log = logging.getLogger("ws.remote")


def register_remote_ws(app):
    """Register remote terminal WebSocket routes on the Flask app."""
    sock.init_app(app)

    @sock.route("/ws/remote/terminal")
    def ws_remote_terminal(ws):
        """Real-time terminal session over WebSocket.

        Client sends:
          {type:"connect", host, port, protocol, username, password, vendor, workspace_id, asset_id?, device_id?}
          {type:"input", session_id, data}
          {type:"disconnect", session_id}

        Server sends:
          {type:"connected", session_id, host, vendor, banner}
          {type:"output", session_id, text}
          {type:"disconnected", session_id}
          {type:"error", message}
        """
        if not _same_origin_ws_request():
            ws.send(json.dumps({"type": "error", "message": "csrf_origin_denied"}))
            return

        sid = None
        workspace_id = ""
        reader_stop = threading.Event()

        def reader_thread():
            from agent.modules.remote.core import get_session
            while not reader_stop.is_set():
                session = get_session(sid)
                if not session or not session.connected:
                    break
                try:
                    chunk = session.recv(timeout=0.5)
                    if chunk:
                        text = chunk.decode("utf-8", errors="replace")
                        session.log.append(text)
                        ws.send(json.dumps({
                            "type": "output", "session_id": sid, "text": text,
                        }, ensure_ascii=False))
                except Exception:
                    _log.warning("remote reader loop error sid=%s", sid, exc_info=True)
                    break
                reader_stop.wait(0.1)

        try:
            while True:
                raw = ws.receive(timeout=300)
                if raw is None:
                    break
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    ws.send(json.dumps({"type": "error", "message": "invalid_json"}))
                    continue

                msg_type = msg.get("type", "")

                if msg_type == "connect":
                    from agent.modules.remote.service import connect_device
                    from workspace.ids import validate_workspace_id

                    try:
                        raw_ws = msg.get("workspace_id", "") or ""
                        if not raw_ws:
                            ws.send(json.dumps({"type": "error", "message": "workspace_id is required"}))
                            continue
                        workspace_id = validate_workspace_id(raw_ws)
                        port = _parse_port(msg.get("port", 22))
                    except ValueError as exc:
                        ws.send(json.dumps({"type": "error", "message": str(exc)}))
                        continue

                    result = connect_device(
                        workspace_id=workspace_id,
                        host=msg.get("host", ""),
                        port=port,
                        protocol=msg.get("protocol", "ssh"),
                        username=msg.get("username", ""),
                        password=msg.get("password", ""),
                        vendor=msg.get("vendor", ""),
                        asset_id=msg.get("asset_id", ""),
                        device_id=msg.get("device_id", ""),
                        terminal_cols=_parse_terminal_size(msg.get("cols"), default=160, lo=20, hi=240),
                        terminal_rows=_parse_terminal_size(msg.get("rows"), default=40, lo=8, hi=80),
                    )

                    if result.get("ok"):
                        sid = result["session_id"]
                        ws.send(json.dumps({
                            "type": "connected",
                            "session_id": sid,
                            "host": result["host"],
                            "vendor": result["vendor"],
                            "banner": result.get("banner", ""),
                        }, ensure_ascii=False))

                        # Read any data buffered before starting the reader thread
                        import time as _t
                        _t.sleep(0.3)
                        from agent.modules.remote.core import get_session
                        s = get_session(sid)
                        if s:
                            early = s.recv(timeout=1.0)
                            if early:
                                text = early.decode("utf-8", errors="replace")
                                s.log.append(text)
                                ws.send(json.dumps({
                                    "type": "output", "session_id": sid, "text": text,
                                }, ensure_ascii=False))

                        reader_stop.clear()
                        th = threading.Thread(target=reader_thread, daemon=True)
                        th.start()
                    else:
                        ws.send(json.dumps({
                            "type": "error",
                            "message": result.get("error", "连接失败"),
                        }, ensure_ascii=False))

                elif msg_type == "input":
                    from agent.modules.remote.service import interactive_input
                    data = _terminal_input_data(msg.get("data", ""))
                    msg_sid = str(msg.get("session_id", "") or "")
                    if not _same_session(msg_sid, sid):
                        ws.send(json.dumps({
                            "type": "error",
                            "session_id": msg_sid,
                            "message": "session_mismatch",
                        }, ensure_ascii=False))
                        continue
                    result = interactive_input(sid or "", data, workspace_id)
                    if not result.get("ok"):
                        ws.send(json.dumps({
                            "type": "error",
                            "session_id": sid,
                            "message": result.get("error", "发送失败"),
                        }, ensure_ascii=False))

                elif msg_type == "resize":
                    from agent.modules.remote.service import resize_terminal
                    msg_sid = str(msg.get("session_id", "") or "")
                    if not _same_session(msg_sid, sid):
                        ws.send(json.dumps({
                            "type": "error",
                            "session_id": msg_sid,
                            "message": "session_mismatch",
                        }, ensure_ascii=False))
                        continue
                    result = resize_terminal(
                        sid or "",
                        _parse_terminal_size(msg.get("cols"), default=160, lo=20, hi=240),
                        _parse_terminal_size(msg.get("rows"), default=40, lo=8, hi=80),
                        workspace_id,
                    )
                    if not result.get("ok"):
                        ws.send(json.dumps({
                            "type": "error",
                            "session_id": sid,
                            "message": result.get("error", "resize_failed"),
                        }, ensure_ascii=False))

                elif msg_type == "disconnect":
                    from agent.modules.remote.service import close_session
                    msg_sid = str(msg.get("session_id", "") or "")
                    if not _same_session(msg_sid, sid):
                        ws.send(json.dumps({
                            "type": "error",
                            "session_id": msg_sid,
                            "message": "session_mismatch",
                        }, ensure_ascii=False))
                        continue
                    close_session(sid or "", workspace_id=workspace_id)
                    ws.send(json.dumps({
                        "type": "disconnected",
                        "session_id": sid,
                    }, ensure_ascii=False))
                    sid = None

                else:
                    ws.send(json.dumps({
                        "type": "error",
                        "message": f"unknown message type: {msg_type}",
                    }, ensure_ascii=False))

        except Exception as e:
            _log.debug("WS remote closed: %s", e)
        finally:
            reader_stop.set()
            if sid:
                from agent.modules.remote.service import close_session
                close_session(sid, workspace_id=workspace_id)


def _parse_port(value) -> int:
    try:
        port = int(value if value not in (None, "") else 22)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid_port") from exc
    if port < 1 or port > 65535:
        raise ValueError("invalid_port")
    return port


def _parse_terminal_size(value, *, default: int, lo: int, hi: int) -> int:
    try:
        parsed = int(value if value not in (None, "") else default)
    except (TypeError, ValueError):
        parsed = default
    return max(lo, min(parsed, hi))


def _terminal_input_data(value) -> str:
    """Return xterm input exactly as emitted.

    xterm sends Enter as ``"\r"``. Translating it to ``"\r\n"`` makes
    many network CLIs execute the command on CR and then treat LF as a
    second empty command, which shows up as a blank line after long
    output. Keep the browser terminal as the single source of truth.
    """
    return str(value or "")


def _same_session(requested_sid: str, active_sid: str | None) -> bool:
    return bool(active_sid and requested_sid and requested_sid == active_sid)


def _same_origin_ws_request() -> bool:
    origin = request.headers.get("Origin")
    return is_allowed_browser_origin(origin, request.host)
