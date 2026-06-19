"""WebSocket handler for real-time agent streaming.

Design:
- WebSocket endpoint: /ws/agent
- Client sends JSON messages, server pushes streaming events.
- Events are pushed via StreamEmitter's realtime callback (thread-local).
- run_turn() runs in a background thread; events flow through queue → WebSocket.

Message protocol:
  Client → Server:
    {"type": "message", "user_input": "...", "session_id": "...", "workspace_id": "default"}

  Server → Client:
    {"type": "event", "name": "...", "data": {...}}  — general event
    {"type": "done", "final_response": "...", "session_id": "...", "turn_id": "...", "tool_calls_count": 0}
    {"type": "error", "message": "..."}
"""

import json
import queue
import threading
import traceback
from flask_sock import Sock

sock = Sock()


def register_ws_routes(app):
    """Register WebSocket routes on the Flask app."""
    sock.init_app(app)

    @sock.route("/ws/agent")
    def ws_agent(ws):
        """WebSocket endpoint for agent message streaming."""
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

                if msg.get("type") != "message":
                    ws.send(json.dumps({"type": "error", "message": f"Unknown type: {msg.get('type')}"}, ensure_ascii=True))
                    continue

                user_input = msg.get("user_input", "")
                if not user_input:
                    ws.send(json.dumps({"type": "error", "message": "Empty user_input"}, ensure_ascii=True))
                    continue

                session_id = msg.get("session_id", "")
                workspace_id = msg.get("workspace_id", "default")
                metadata = msg.get("metadata", {})

                # Event queue for thread-safe communication
                event_queue = queue.Queue()

                def realtime_callback(event):
                    try:
                        event_queue.put(event, block=False)
                    except queue.Full:
                        pass

                # Register callback on StreamEmitter (thread-local)
                from agent.runtime.query_engine import StreamEmitter
                StreamEmitter.set_realtime_callback(realtime_callback)

                error_holder = {"error": None}

                thread = threading.Thread(
                    target=_run_agent_thread,
                    args=(user_input, session_id, workspace_id, metadata, event_queue, error_holder),
                    daemon=True,
                )
                thread.start()

                # Stream events from queue to WebSocket
                while True:
                    try:
                        event = event_queue.get(timeout=0.1)
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
                        StreamEmitter.clear_realtime_callback()
                        return

                StreamEmitter.clear_realtime_callback()

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


def _run_agent_thread(user_input, session_id, workspace_id, metadata, event_queue, error_holder):
    """Run agent in background thread."""
    try:
        from agent.app.service import get_default_agent_app
        app = get_default_agent_app()

        result = app.submit_user_message(
            user_input=user_input,
            session_id=session_id,
            workspace_id=workspace_id,
            metadata=metadata,
        )

        result_payload = result.to_dict()

        import sys as _sys
        print(f"[ws-agent] final_response_len={len(result_payload.get('final_response', ''))}", file=_sys.stderr)

        if result_payload.get("final_response"):
            from agent.llm.runtime import sanitize_provider_output
            result_payload["final_response"], _ = sanitize_provider_output(result_payload["final_response"])

        # Push collected events from AgentResult.
        for ev in result_payload.get("events", []):
            try:
                event_queue.put({"type": "event", "name": ev.get("type", "event"), "data": ev}, timeout=0.5)
            except queue.Full:
                pass

        # Compute tool_calls_count and extract tool_calls + metadata
        tool_calls = result_payload.get("tool_calls", [])
        tool_calls_count = len(tool_calls) or len([
            e for e in result_payload.get("events", [])
            if e.get("type") == "tool_call"
        ])
        metadata = result_payload.get("metadata", {})
        if not metadata:
            metadata = {}

        # Use the actual session_id from result (may differ for newly created sessions)
        resolved_session_id = result_payload.get("session_id") or session_id or ""

        event_queue.put({
            "type": "done",
            "session_id": resolved_session_id,
            "turn_id": result_payload.get("turn_id", ""),
            "trace_id": result_payload.get("trace_id", ""),
            "final_response": result_payload.get("final_response", ""),
            "events": result_payload.get("events", []),
            "tool_calls_count": tool_calls_count,
            "tool_calls": tool_calls,
            "metadata": metadata,
            "errors": result_payload.get("errors", []),
            "warnings": result_payload.get("warnings", []),
            "tool_decision": result_payload.get("tool_decision", {}),
            "no_tool_reason": result_payload.get("no_tool_reason", ""),
        })

    except Exception as e:
        traceback.print_exc()
        error_holder["error"] = str(e)[:500]
        event_queue.put({"type": "error", "message": str(e)[:500]})
    finally:
        event_queue.put(None)
