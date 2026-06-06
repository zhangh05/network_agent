# backend/api/workspace.py
"""Workspace API — list, state, runs, artifacts."""

import json
from flask import jsonify
from backend.core.paths import WORKSPACES_DIR


def handle_workspace_status():
    """Global workspace status."""
    from workspace.manager import list_workspaces
    return jsonify({
        "ok": True,
        "workspace_root": str(WORKSPACES_DIR),
        "workspaces": list_workspaces(),
    })
