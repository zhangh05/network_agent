"""Tool approval API routes — pause/resume for high-risk tool calls."""

from flask import jsonify, request


def register_approval_routes(app):
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
        from agent.approval import get_approval_store
        store = get_approval_store()
        data = request.get_json(silent=True) or {}
        allowed = bool(data.get("allowed", False))
        req = store.resolve(approval_id, allowed)
        if req is None:
            return jsonify({"ok": False, "error": "approval not found or already resolved"}), 404
        return jsonify({
            "ok": True,
            "approval_id": approval_id,
            "allowed": allowed,
        })
