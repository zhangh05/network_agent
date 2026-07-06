"""WebSocket handler for real-time agent streaming.

Design:
- WebSocket endpoint: /ws/agent
- Client sends JSON messages, server pushes live StreamEmitter events.
- Business execution still goes through AgentApp.submit_user_message(), so
  HTTP and WebSocket share the same Agent Runtime contract.
- Job lifecycle (create, update runs, progress) is handled here, mirroring
  the HTTP route in agent_routes.py.

Message protocol:
  Client → Server:
    {"type": "message", "user_input": "...", "session_id": "...", "workspace_id": "default"}

  Server → Client:
    {"type": "event", "name": "...", "data": {...}}  — live event
    {"type": "done", "final_response": "...", "session_id": "...", "turn_id": "...", "tool_calls_count": 0}
    {"type": "error", "message": "..."}
"""

import json
import logging
import queue
import threading
import traceback
from flask import request
from flask_sock import Sock
from backend.core.auth import is_allowed_browser_origin

sock = Sock()
_log = logging.getLogger("ws.agent")
_MAX_WS_INPUT_LENGTH = 65536
_MAX_WS_METADATA_JSON = 16384

# v3.16: Global connection registry for broadcasting system events
# (job_updated, inspection_progress, run_status) to all active clients.
_active_ws_connections: dict[str, object] = {}  # ws_key → ws connection
_active_ws_lock = threading.Lock()


def broadcast_ws_event(event: dict) -> None:
    """Push a system event to all connected WebSocket clients."""
    payload = json.dumps({"type": "event", "name": event["name"], "data": event.get("data", {})}, ensure_ascii=True, default=str)
    dead: list[str] = []
    with _active_ws_lock:
        for key, ws in list(_active_ws_connections.items()):
            try:
                ws.send(payload)
            except Exception:
                dead.append(key)
    for key in dead:
        with _active_ws_lock:
            _active_ws_connections.pop(key, None)


def register_ws_routes(app):
    """Register WebSocket routes on the Flask app."""
    sock.init_app(app)

    @sock.route("/ws/agent")
    def ws_agent(ws):
        """WebSocket endpoint for agent message streaming."""
        if not _same_origin_ws_request():
            ws.send(json.dumps({"type": "error", "message": "csrf_origin_denied"}))
            return

        # When auth is enabled, enforce token on the first message
        _auth_checked = False

        try:
            while True:
                raw = ws.receive(timeout=300)
                if raw is None:
                    break

                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    ws.send(json.dumps({"type": "error", "message": "Invalid JSON"}, ensure_ascii=True))
                    continue

                # System WebSocket — register for broadcasts, skip agent turn
                if msg.get("type") == "ping":
                    ws_key = f"{id(ws)}_{threading.current_thread().ident}"
                    with _active_ws_lock:
                        _active_ws_connections[ws_key] = ws
                    ws.send(json.dumps({"type": "pong", "message": "connected"}, ensure_ascii=True))
                    continue

                if msg.get("type") != "message":
                    ws.send(json.dumps({"type": "error", "message": f"Unknown type: {msg.get('type')}"}, ensure_ascii=True))
                    continue

                # P0-16: token in message field (not header), checked once per connection.
                # Origin check bypassed when token is valid (CSRF double-track).
                if not _auth_checked:
                    from backend.core.auth import _is_auth_enabled, _get_api_token
                    import hmac as _hmac
                    if _is_auth_enabled() and _get_api_token():
                        if not _hmac.compare_digest(str(msg.get("auth_token", "")), _get_api_token()):
                            ws.send(json.dumps({"type": "error", "message": "unauthorized"}, ensure_ascii=True))
                            return
                    _auth_checked = True

                user_input = msg.get("user_input", msg.get("message", ""))
                if not user_input:
                    ws.send(json.dumps({"type": "error", "message": "Empty user_input"}, ensure_ascii=True))
                    continue
                if len(str(user_input)) > _MAX_WS_INPUT_LENGTH:
                    ws.send(json.dumps({"type": "error", "message": "message too long (max 64KB)"}, ensure_ascii=True))
                    continue

                session_id = msg.get("session_id", "") or ""
                workspace_id = msg.get("workspace_id", "") or ""
                if not workspace_id:
                    ws.send(json.dumps({"type": "error", "message": "workspace_id is required"}, ensure_ascii=True))
                    continue
                try:
                    from workspace.ids import validate_workspace_id, validate_session_id
                    workspace_id = validate_workspace_id(workspace_id)
                    if session_id:
                        session_id = validate_session_id(session_id)
                except ValueError:
                    ws.send(json.dumps({
                        "type": "error",
                        "message": "Invalid session_id or workspace_id",
                    }, ensure_ascii=True))
                    continue

                metadata = msg.get("metadata", {})
                if not isinstance(metadata, dict):
                    metadata = {}
                try:
                    from backend.core.agent_contract import metadata_size, normalize_metadata
                    if metadata_size(metadata) > _MAX_WS_METADATA_JSON:
                        ws.send(json.dumps({"type": "error", "message": "metadata too large (max 16KB)"}, ensure_ascii=True))
                        continue
                except Exception:
                    _log.warning("WS metadata normalize failed, resetting to {}", exc_info=True)
                    metadata = {}
                from backend.core.agent_contract import normalize_metadata
                metadata = normalize_metadata(metadata, transport="websocket", stream_mode="live")

                # Event queue for thread-safe communication
                event_queue = queue.Queue(maxsize=1000)
                error_holder = {"error": None}
                stats = {"live_events": 0}

                thread = threading.Thread(
                    target=_run_agent_thread,
                    args=(user_input, session_id, workspace_id, metadata, event_queue, error_holder, stats),
                    daemon=True,
                )
                thread.start()

                # Stream events from queue to WebSocket
                while True:
                    try:
                        event = event_queue.get(timeout=0.01)
                    except queue.Empty:
                        if not thread.is_alive():
                            try:
                                event = event_queue.get(timeout=0.5)
                            except queue.Empty:
                                break
                        else:
                            continue

                    if event is None:
                        break

                    try:
                        ws.send(json.dumps(event, ensure_ascii=True, default=str))
                    except Exception:
                        return

                if error_holder["error"]:
                    try:
                        ws.send(json.dumps({"type": "error", "message": error_holder["error"]}, ensure_ascii=True))
                    except Exception:
                        pass

        except Exception as e:
            try:
                ws.send(json.dumps({"type": "error", "message": f"WebSocket error: {str(e)[:200]}"}, ensure_ascii=True))
            except Exception:
                pass
            finally:
                try:
                    from agent.runtime.query_engine import StreamEmitter
                    StreamEmitter.clear_realtime_callback()
                except Exception:
                    pass

    return app


def _same_origin_ws_request() -> bool:
    origin = request.headers.get("Origin")
    return is_allowed_browser_origin(origin, request.host)


def _run_agent_thread(user_input, session_id, workspace_id, metadata, event_queue, error_holder, stats):
    """Run agent in background thread through the shared AgentApp contract."""
    from agent.runtime.query_engine import StreamEmitter

    def realtime_callback(event):
        try:
            live_count = int(stats.get("live_events", 0)) + 1
            stats["live_events"] = live_count
            seq = int(stats.get("event_seq", 0)) + 1
            stats["event_seq"] = seq
            if isinstance(event, dict) and event.get("type") == "token":
                try:
                    event_queue.put({"type": "token", "content": event.get("content", ""), "seq": seq}, timeout=0.2)
                except queue.Full:
                    pass
            else:
                name = event.get("type", event.get("name", "event")) if isinstance(event, dict) else "event"
                # v3.10: Surface tool calls as live events for inline display
                data = event
                if name in ("tool_call", "tool_result") and isinstance(event, dict):
                    data = {
                        **event,
                        "tool_id": event.get("tool_id", event.get("name", "")),
                        "ok": event.get("ok", event.get("status") == "ok"),
                        "summary": event.get("summary", event.get("message", "")),
                    }
                event_queue.put({
                    "type": "event",
                    "name": name,
                    "data": data,
                    "seq": seq,
                }, timeout=0.2)
        except Exception:
            _log.warning("realtime_callback event push failed seq=%s", stats.get("event_seq"), exc_info=True)

    try:
        # StreamEmitter stores callbacks thread-locally, so it must be set in
        # the same worker thread that runs AgentApp.submit_user_message().
        StreamEmitter.set_realtime_callback(realtime_callback)

        from agent.app.service import get_default_agent_app
        app = get_default_agent_app()

        result = app.submit_user_message(
            user_input=user_input,
            session_id=session_id,
            workspace_id=workspace_id,
            metadata=metadata,
        )

        result_payload = result.to_dict()

        # ── Job lifecycle (unified via jobs.lifecycle) ──
        effective_session_id = session_id or result_payload.get("session_id", "")
        if effective_session_id:
            try:
                from jobs.lifecycle import attach_run_to_session_job
                attach_run_to_session_job(
                    ws_id=workspace_id,
                    session_id=effective_session_id,
                    run_id=result_payload.get("turn_id", ""),
                    tool_call_count=len(result_payload.get("tool_calls", [])),
                    user_input=user_input,
                )
            except Exception:
                _log.exception("WS job lifecycle error session=%s ws=%s", effective_session_id, workspace_id)

        if result_payload.get("final_response"):
            from agent.llm.runtime import sanitize_provider_output
            result_payload["final_response"], stripped = sanitize_provider_output(result_payload["final_response"])
            if stripped:
                result_payload.setdefault("metadata", {})["reasoning_stripped"] = True

        # Fallback: if no live events were emitted, replay collected events so
        # older runtime paths still produce observable progress data.
        if int(stats.get("live_events", 0)) == 0:
            for ev in result_payload.get("events", []):
                try:
                    event_queue.put({"type": "event", "name": ev.get("type", "event"), "data": ev}, timeout=0.5)
                except queue.Full:
                    pass

        tool_calls = result_payload.get("tool_calls", [])
        tool_calls_count = len(tool_calls) or len([
            e for e in result_payload.get("events", [])
            if e.get("type") == "tool_call"
        ])
        metadata_out = result_payload.get("metadata", {}) or {}
        metadata_out.setdefault("transport", "websocket")
        metadata_out.setdefault("stream_mode", "live" if int(stats.get("live_events", 0)) else "event_replay_fallback")

        resolved_session_id = result_payload.get("session_id") or session_id or ""

        # Send done event first — so frontend sees it immediately
        event_queue.put({
            "type": "done",
            "session_id": resolved_session_id,
            "turn_id": result_payload.get("turn_id", ""),
            "trace_id": result_payload.get("trace_id", ""),
            "final_response": result_payload.get("final_response", ""),
            "events": result_payload.get("events", []),
            "tool_calls_count": tool_calls_count,
            "tool_calls": tool_calls,
            "metadata": metadata_out,
            "errors": result_payload.get("errors", []),
            "warnings": result_payload.get("warnings", []),
            "tool_decision": result_payload.get("tool_decision", {}),
            "no_tool_reason": result_payload.get("no_tool_reason", ""),
            "stream_seq": stats.get("event_seq", 0),
            "active_module": result_payload.get("active_module", ""),
            "capability": result_payload.get("capability", ""),
            "error_type": result_payload.get("error_type", ""),
        })

    except Exception as e:
        traceback.print_exc()
        error_holder["error"] = str(e)[:500]
        event_queue.put({"type": "error", "message": str(e)[:500]})
    finally:
        try:
            StreamEmitter.clear_realtime_callback()
        except Exception:
            pass
        event_queue.put(None)
