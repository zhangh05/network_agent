# backend/api/agent_routes.py
"""Agent API routes — v0.6 Codex-style runtime endpoint."""

from flask import Blueprint, request, jsonify

agent_bp = Blueprint("agent", __name__, url_prefix="/api/agent")


@agent_bp.route("/message", methods=["POST"])
def agent_message():
    """POST /api/agent/message — submit user message via AgentApp."""
    data = request.get_json(silent=True) or {}
    user_input = data.get("message", data.get("text", ""))
    session_id = data.get("session_id", None)
    workspace_id = data.get("workspace_id", "default")
    metadata = data.get("metadata", {})

    if not user_input:
        return jsonify({"ok": False, "error": "message is required"}), 400

    try:
        from agent.app.service import get_default_agent_app
        app = get_default_agent_app()
        result = app.submit_user_message(
            user_input=user_input,
            session_id=session_id,
            workspace_id=workspace_id,
            metadata=metadata,
        )
        return jsonify(result.to_dict())
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)[:500]}), 500
