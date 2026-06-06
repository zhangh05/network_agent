"""Workspace identifier validation.

Workspace IDs are used as path segments under the workspace root, so keep the
accepted shape intentionally narrow and shared by all storage layers.
"""

import re

_WORKSPACE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def validate_workspace_id(ws_id: str) -> str:
    """Return a valid workspace ID or raise ValueError."""
    if not isinstance(ws_id, str):
        raise ValueError("invalid_workspace_id")
    if not _WORKSPACE_ID_RE.fullmatch(ws_id):
        raise ValueError("invalid_workspace_id")
    return ws_id


def is_valid_workspace_id(ws_id: str) -> bool:
    try:
        validate_workspace_id(ws_id)
        return True
    except ValueError:
        return False
