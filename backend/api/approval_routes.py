"""Tool approval API routes — pause/resume for high-risk tool calls.

v3.2.0 (Guardian): Expanded the approval API surface.
- GET  /api/agent/approvals/pending        — list pending approvals
- POST /api/agent/approvals/<id>/resolve   — resolve an approval
- GET  /api/agent/approvals/history        — audit history (resolved)
- GET  /api/agent/approvals/sse            — real-time event stream (SSE)
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
from typing import Iterator

from flask import Response, jsonify, request, stream_with_context


def _admin_token_allowed() -> bool:
    expected = os.environ.get("NETWORK_AGENT_ADMIN_TOKEN", "")
    if not expected:
        return True
    supplied = request.headers.get("X-Admin-Token", "")
    if not supplied:
        return False
    import hmac

    return hmac.compare_digest(supplied, expected)


def register_approval_routes(app) -> None:
    """Register approval endpoints on the Flask app."""

    @app.route("/api/agent/approvals/pending")
    def api_approvals_pending():
        """GET pending approvals, optionally filtered by session_id."""
        from agent.approval import get_approval_store
        store = get_approval_store()
        session_id = request.args.get("session_id", "")
        pending = store.get_pending(session_id)
        return jsonify({
            "ok": True,
            "pending": pending,
            "count": len(pending),
        })

    @app.route("/api/agent/approvals/<approval_id>/resolve", methods=["POST"])
    def api_approval_resolve(approval_id):
        """POST resolve an approval — body: {"allowed": true/false}."""
        if not _admin_token_allowed():
            return jsonify({"ok": False, "error": "admin_access_required"}), 403
        from agent.approval import get_approval_store
        store = get_approval_store()
        data = request.get_json(silent=True) or {}
        allowed = bool(data.get("allowed", False))
        resolver = str(data.get("resolver") or "user")
        reason = str(data.get("reason") or "")
        req = store.resolve(approval_id, allowed, resolver=resolver, reason=reason)
        if req is None:
            return jsonify({"ok": False, "error": "approval not found or already resolved"}), 404
        return jsonify({
            "ok": True,
            "approval_id": approval_id,
            "allowed": allowed,
        })

    @app.route("/api/agent/approvals/history")
    def api_approvals_history():
        """GET resolved approval history (Guardian audit)."""
        from agent.approval import get_approval_store
        store = get_approval_store()
        session_id = request.args.get("session_id", "")
        tool_id = request.args.get("tool_id", "")
        try:
            limit = max(1, min(int(request.args.get("limit", "100")), 500))
        except (TypeError, ValueError):
            limit = 100
        try:
            since = float(request.args.get("since", "0") or 0)
        except (TypeError, ValueError):
            since = 0.0
        records = store.get_history(
            session_id=session_id, tool_id=tool_id,
            limit=limit, since_ts=since,
        )
        return jsonify({
            "ok": True,
            "history": records,
            "count": len(records),
        })

    @app.route("/api/agent/approvals/sse")
    def api_approvals_sse():
        """Server-Sent Events stream of approval create/resolve events.

        Subscribes to the in-process event bus and forwards each event as
        an SSE 'message' frame. Replaces the frontend 5s polling loop.
        """
        from agent.approval import get_event_bus
        bus = get_event_bus()

        # Per-connection queue: the bus puts events here, the SSE generator
        # yields them. A keepalive ping is emitted every 25s so proxies and
        # browsers don't drop the connection.
        q: "queue.Queue[dict]" = queue.Queue(maxsize=64)

        def _on_event(event) -> None:
            try:
                q.put_nowait({
                    "kind": event.kind,
                    "approval_id": event.approval_id,
                    "session_id": event.session_id,
                    "tool_id": event.tool_id,
                    "allowed": event.allowed,
                    "payload": event.payload,
                    "ts": time.time(),
                })
            except queue.Full:
                pass  # drop if client is too slow; keepalive still flows

        unsubscribe = bus.subscribe(_on_event)

        @stream_with_context
        def _stream() -> Iterator[bytes]:
            try:
                # Send an initial comment so the browser opens the stream.
                yield b": connected\n\n"
                while True:
                    try:
                        evt = q.get(timeout=25.0)
                        yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n".encode("utf-8")
                    except queue.Empty:
                        # keepalive ping (SSE comment line — ignored by EventSource)
                        yield b": ping\n\n"
            except GeneratorExit:
                pass
            finally:
                unsubscribe()

        return Response(
            _stream(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )
