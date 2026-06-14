# backend/api/agent_routes.py
"""Agent API routes — v2.1.1 unified entry point."""

import logging
from flask import request, jsonify
from backend.core.errors import (
    bad_request, server_error, invalid_workspace, invalid_session, too_large,
)

_log = logging.getLogger("agent_routes")


def _validated_ws_id(ws_id: str):
    from workspace.ids import validate_workspace_id
    try:
        ws = validate_workspace_id(ws_id)
        if not ws:
            return "", invalid_workspace()
        return ws, None
    except ValueError:
        return "", invalid_workspace()


def _validated_session_id(sid: str):
    if not sid:
        return sid, None
    from workspace.ids import validate_session_id
    try:
        s = validate_session_id(sid)
        if not s:
            return "", invalid_session()
        return s, None
    except ValueError:
        return "", invalid_session()


def agent_message():
    """POST /api/agent/message — submit user message via AgentApp."""
    data = request.get_json(silent=True) or {}
    user_input = data.get("message", data.get("text", ""))

    # Validate workspace_id
    workspace_id = data.get("workspace_id", "default")
    ws_id, ws_err = _validated_ws_id(workspace_id)
    if ws_err:
        return ws_err

    # Validate session_id (optional but must be valid format if provided)
    session_id = data.get("session_id", None)
    if session_id:
        sid, s_err = _validated_session_id(session_id)
        if s_err:
            return s_err
        session_id = sid

    if not user_input:
        return bad_request("message is required")

    # Cap user input length to prevent OOM
    MAX_INPUT_LENGTH = 65536  # 64KB
    if len(user_input) > MAX_INPUT_LENGTH:
        return too_large("message too long (max 64KB)")

    metadata = data.get("metadata") or {}
    # Cap metadata size to prevent abuse
    try:
        meta_json = jsonify(metadata).get_data(as_text=True) if metadata else "{}"
        if len(meta_json) > 16384:
            return too_large("metadata too large (max 16KB)")
    except Exception:
        metadata = {}

    try:
        from agent.app.service import get_default_agent_app
        app = get_default_agent_app()
        result = app.submit_user_message(
            user_input=user_input,
            session_id=session_id,
            workspace_id=ws_id,
            metadata=metadata,
        )
        payload = result.to_dict()
        if payload.get("final_response"):
            from agent.llm.runtime import sanitize_provider_output
            payload["final_response"], stripped = sanitize_provider_output(payload["final_response"])
            if stripped:
                payload.setdefault("metadata", {})["reasoning_stripped"] = True
        return jsonify(payload)
    except Exception as e:
        _log.exception("agent_message failed")
        return server_error("agent execution failed")
