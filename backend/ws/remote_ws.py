"""Remote terminal WebSocket — real-time interactive device session.

Uses flask_sock (same pattern as agent_ws.py).
"""

import json
import logging
import threading
from urllib.parse import urlparse

from flask import request
from flask_sock import Sock

sock = Sock()
_log = logging.getLogger("ws.remote")


def register_remote_ws(app):
    """Register remote terminal WebSocket routes on the Flask app."""
    sock.init_app(app)

    @sock.route("/ws/remote/terminal")
    def ws_remote_terminal(ws):
        """Real-time terminal session over WebSocket.

        Client sends:
          {type:"connect", host, port, protocol, username, password, vendor, workspace_id}
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
                    break
                reader_stop.wait(0.1)

        try:
            while True:
                raw = ws.receive(timeout=300)
                if raw is None:
                    break
                try:
                    msg = json.loads(raw)
                except Exception:
                    ws.send(json.dumps({"type": "error", "message": "invalid_json"}))
                    continue

                msg_type = msg.get("type", "")

                if msg_type == "connect":
                    from agent.modules.remote.service import connect_device
                    from workspace.ids import validate_workspace_id

                    try:
                        workspace_id = validate_workspace_id(msg.get("workspace_id", "default") or "default")
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
                    from agent.modules.remote.core import send_interactive
                    data = msg.get("data", "")
                    if data == "\r":
                        data = "\r\n"
                    result = send_interactive(msg.get("session_id", ""), data)
                    if not result.get("ok"):
                        ws.send(json.dumps({
                            "type": "error",
                            "session_id": msg.get("session_id", ""),
                            "message": result.get("error", "发送失败"),
                        }, ensure_ascii=False))

                elif msg_type == "disconnect":
                    from agent.modules.remote.service import close_session
                    close_session(msg.get("session_id", ""))
                    ws.send(json.dumps({
                        "type": "disconnected",
                        "session_id": msg.get("session_id", ""),
                    }, ensure_ascii=False))

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
                close_session(sid)


def _parse_port(value) -> int:
    try:
        port = int(value if value not in (None, "") else 22)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid_port") from exc
    if port < 1 or port > 65535:
        raise ValueError("invalid_port")
    return port


def _same_origin_ws_request() -> bool:
    origin = request.headers.get("Origin")
    if not origin:
        return True
    try:
        return urlparse(origin).netloc == request.host.split("@")[-1]
    except Exception:
        return False
