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
from flask_sock import Sock

sock = Sock()
_log = logging.getLogger("ws.agent")
_MAX_WS_INPUT_LENGTH = 65536
_MAX_WS_METADATA_JSON = 16384


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

                user_input = msg.get("user_input", msg.get("message", ""))
                if not user_input:
                    ws.send(json.dumps({"type": "error", "message": "Empty user_input"}, ensure_ascii=True))
                    continue
                if len(str(user_input)) > _MAX_WS_INPUT_LENGTH:
                    ws.send(json.dumps({"type": "error", "message": "message too long (max 64KB)"}, ensure_ascii=True))
                    continue

                session_id = msg.get("session_id", "") or ""
                workspace_id = msg.get("workspace_id", "default") or "default"
                try:
                    from workspace.ids import validate_workspace_id, validate_session_id
                    workspace_id = validate_workspace_id(workspace_id)
                    if session_id:
                        session_id = validate_session_id(session_id)
                except Exception:
                    ws.send(json.dumps({
                        "type": "error",
                        "message": "Invalid session_id or workspace_id",
                    }, ensure_ascii=True))
                    continue

                metadata = msg.get("metadata", {})
                if not isinstance(metadata, dict):
                    metadata = {}
                try:
                    from backend.api.agent_contract import metadata_size, normalize_metadata
                    if metadata_size(metadata) > _MAX_WS_METADATA_JSON:
                        ws.send(json.dumps({"type": "error", "message": "metadata too large (max 16KB)"}, ensure_ascii=True))
                        continue
                except Exception:
                    metadata = {}
                from backend.api.agent_contract import normalize_metadata
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


def _run_agent_thread(user_input, session_id, workspace_id, metadata, event_queue, error_holder, stats):
    """Run agent in background thread through the shared AgentApp contract."""
    from agent.runtime.query_engine import StreamEmitter

    def realtime_callback(event):
        try:
            stats["live_events"] = int(stats.get("live_events", 0)) + 1
            if isinstance(event, dict) and event.get("type") == "token":
                # Pass token events through directly for streaming display
                event_queue.put(event, timeout=0.2)
            else:
                event_queue.put({
                    "type": "event",
                    "name": event.get("type", event.get("name", "event")) if isinstance(event, dict) else "event",
                    "data": event,
                }, timeout=0.2)
        except Exception:
            pass

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

        # ── Job lifecycle (mirrors agent_routes.py) ──
        effective_session_id = session_id or result_payload.get("session_id", "")
        if effective_session_id:
            try:
                from jobs.store import get_job, update_job, list_jobs
                from jobs.manager import create_job, mark_running, update_progress

                job_id = None
                for j in list_jobs(ws_id=workspace_id, limit=500):
                    p = j.get("payload", {}) or {}
                    if p.get("session_id") == effective_session_id and j.get("status") in ("created","queued","running","succeeded","failed","paused","cancelled"):
                        job_id = j.get("job_id", "")
                        _log.debug("WS job found: %s for session=%s", job_id, effective_session_id)
                        break

                if not job_id:
                    title = user_input[:40].replace("\n", " ")
                    try:
                        from workspace.session_store import get_session
                        s = get_session(effective_session_id, workspace_id)
                        if s and s.get("title"):
                            title = s["title"]
                    except Exception:
                        pass
                    j = create_job(workspace_id=workspace_id, job_type="agent_run", title=title,
                                   payload={"session_id": effective_session_id}, created_by="api")
                    job_id = j.job_id
                    _log.info("WS job created: %s for session=%s title=%.40s", job_id, effective_session_id, title)

                rec = get_job(workspace_id, job_id)
                if rec and rec.status in ("created", "queued"):
                    mark_running(workspace_id, job_id)
                    _log.debug("WS job marked running: %s", job_id)

                run_id = result_payload.get("run_id", "")
                if run_id and job_id:
                    rec = get_job(workspace_id, job_id)
                    new_ids = list(getattr(rec, "run_ids", None) or [])
                    try:
                        from workspace.session_store import get_session
                        s = get_session(effective_session_id, workspace_id)
                        if s:
                            for rid in (s.get("run_ids") or []):
                                if rid not in new_ids:
                                    new_ids.append(rid)
                    except Exception:
                        pass
                    if run_id not in new_ids:
                        new_ids.append(run_id)
                    tc = len(result_payload.get("tool_calls", []))
                    update_job(workspace_id, job_id, {"run_ids": new_ids})
                    update_progress(workspace_id, job_id, current=len(new_ids),
                                    message=f"{len(new_ids)}轮 | {tc}工具调用")
                    _log.info("WS job updated: %s runs=%d tools=%d", job_id, len(new_ids), tc)
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
        })

        # v3.3.4: Run deferred finalization AFTER done event — user sees response immediately
        try:
            from agent.runtime.result_builder import run_deferred_finalization
            run_deferred_finalization(result)
        except Exception:
            pass

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
