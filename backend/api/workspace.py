# backend/api/workspace.py

from flask import jsonify
from backend.core.paths import WORKSPACES_DIR


def handle_workspace_status():
    return jsonify({
        "ok": True,
        "workspace_root": str(WORKSPACES_DIR),
        "sessions": [],
        "active_session": None,
    })
