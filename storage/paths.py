# storage/paths.py
"""Unified workspace path resolution.

All storage code and module code MUST use these functions
instead of defining their own WS_ROOT.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def get_workspace_root() -> Path:
    """Return the workspace root directory, respecting env vars."""
    env = os.environ.get("NA_WORKSPACE_ROOT") or os.environ.get("NETWORK_AGENT_WORKSPACE_DIR")
    return Path(env if env else REPO_ROOT / "workspaces").resolve()


def workspace_root(workspace_id: str) -> Path:
    """Return the root directory for a specific workspace."""
    from workspace.ids import validate_workspace_id
    return get_workspace_root() / validate_workspace_id(workspace_id)


def ensure_workspace_storage_dirs(workspace_id: str) -> None:
    """Create all standard storage directories for a workspace."""
    ws = workspace_root(workspace_id)
    for rel in [
        "files/user_upload/original",
        "files/user_upload/staged",
        "files/agent_output/config",
        "files/agent_output/pcap",
        "files/agent_output/report",
        "files/agent_output/export",
        "files/agent_output/message",
        "files/knowledge/source",
        "files/knowledge/normalized",
        "files/tmp",
        # System dirs
        "index",
        "context",
        "sessions",
        "runs",
        "sys",
        "inbox",
    ]:
        (ws / rel).mkdir(parents=True, exist_ok=True)
