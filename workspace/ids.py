"""Workspace identifier validation.

Workspace IDs are used as path segments under the workspace root, so keep the
accepted shape intentionally narrow and shared by all storage layers.
Session IDs similarly need validation to prevent path traversal and
injection into file paths.
"""

import re

# Default workspace ID used project-wide
DEFAULT_WORKSPACE_ID = "default"

_WORKSPACE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

# Session IDs are generated as uuid4 hex[:16] — 16 hex chars.
# Allow any reasonable alphanumeric+hyphen ID, but reject path separators,
# null bytes, and characters dangerous in file paths.
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_SESSION_ID_BLOCKED = {"", ".", "..", "default"}  # reserved


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


def validate_session_id(sid: str) -> str:
    """Return a valid session ID or raise ValueError.

    Blocks:
      - Non-string types
      - Empty strings or reserved names ('.', '..', 'default')
      - Characters outside [A-Za-z0-9_-]
      - Leading dot or hyphen
      - Length > 64
      - Path separators (/ or \\)
      - Null bytes
    """
    if not isinstance(sid, str):
        raise ValueError("invalid_session_id")
    sid = sid.strip()
    if not sid or sid in _SESSION_ID_BLOCKED:
        raise ValueError("invalid_session_id")
    if len(sid) > 64:
        raise ValueError("invalid_session_id")
    if "\x00" in sid:
        raise ValueError("invalid_session_id")
    if "/" in sid or "\\" in sid:
        raise ValueError("invalid_session_id")
    if not _SESSION_ID_RE.fullmatch(sid):
        raise ValueError("invalid_session_id")
    return sid


def is_valid_session_id(sid: str) -> bool:
    try:
        validate_session_id(sid)
        return True
    except ValueError:
        return False
