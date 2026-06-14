# backend/api/agent_status.py
"""Agent status endpoint — v2.1.1 unified."""

from flask import jsonify
from agent.legacy.graph import get_runtime_status


def handle_agent_status():
    """GET /api/agent/status — return agent runtime status."""
    return jsonify(get_runtime_status())
