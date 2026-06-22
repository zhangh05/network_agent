"""Remote terminal WebSocket — real-time interactive device session."""

import json
import logging
import threading

_log = logging.getLogger("ws.remote")


def register_remote_ws(ws_manager, app):
    """Register remote terminal WebSocket routes."""

    @app.route("/ws/remote/terminal", websocket=True)
    def ws_remote_terminal():
        """Real-time terminal session over WebSocket.

        Client sends:
          {type:"connect", host, port, protocol, username, password, vendor}
          {type:"input", session_id, data}
          {type:"disconnect", session_id}

        Server sends:
          {type:"banner", session_id, text}
          {type:"output", session_id, text}
          {type:"error", session_id, message}
          {type:"disconnected", session_id}
        """
        from flask_sock import Sock

        ws = ws_manager.get_ws()
        if ws is None:
            return

        try:
            while True:
                raw = ws.receive()
                if raw is None:
                    break
                msg = json.loads(raw)
                msg_type = msg.get("type", "")

                if msg_type == "connect":
                    _handle_ws_connect(ws, msg)
                elif msg_type == "input":
                    _handle_ws_input(ws, msg)
                elif msg_type == "disconnect":
                    _handle_ws_disconnect(ws, msg)
                else:
                    ws.send(json.dumps({"type": "error", "message": f"unknown type: {msg_type}"}))

        except Exception as e:
            _log.debug("WS remote terminal closed: %s", e)


def _handle_ws_connect(ws, msg):
    from agent.modules.remote.service import connect_device

    result = connect_device(
        workspace_id=msg.get("workspace_id", "default"),
        host=msg.get("host", ""),
        port=int(msg.get("port", 22)),
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
        }))

        # Start reading goroutine-like thread
        def reader():
            from agent.modules.remote.core import get_session
            session = get_session(sid)
            if not session:
                return
            import time
            while session.connected:
                try:
                    import time as t
                    buf = session.read_all(timeout=0.5)
                    if buf:
                        text = buf.decode("utf-8", errors="replace")
                        session.log.append(text)
                        try:
                            ws.send(json.dumps({"type": "output", "session_id": sid, "text": text}))
                        except Exception:
                            break
                    t.sleep(0.1)
                except Exception:
                    break

        threading.Thread(target=reader, daemon=True).start()
    else:
        ws.send(json.dumps({"type": "error", "message": result.get("error", "连接失败")}))


def _handle_ws_input(ws, msg):
    from agent.modules.remote.core import send_interactive
    sid = msg.get("session_id", "")
    data = msg.get("data", "")

    if data == "\r" or data == "\n":
        result = send_interactive(sid, "\r\n")
    else:
        result = send_interactive(sid, data)

    if not result.get("ok"):
        ws.send(json.dumps({"type": "error", "session_id": sid, "message": result.get("error", "")}))


def _handle_ws_disconnect(ws, msg):
    from agent.modules.remote.service import close_session
    sid = msg.get("session_id", "")
    close_session(sid)
    ws.send(json.dumps({"type": "disconnected", "session_id": sid}))
