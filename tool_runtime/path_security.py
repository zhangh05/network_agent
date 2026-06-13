# tool_runtime/path_security.py
"""Safe workspace path resolver — blocks path traversal, symlink escape, and encoding bypass.

All workspace file paths MUST go through this resolver. It guarantees:
1. Path resolves within the workspace root
2. No ../ (or encoded variants) escape
3. No absolute path injection
4. No symlink escape to outside workspace
5. No Windows drive-path injection (C:\\, D:\\)
6. No URL-encoded traversal (%2e%2e/)

Usage:
    from tool_runtime.path_security import safe_workspace_path
    target = safe_workspace_path("workspace_id", "subdir/file.txt")
    # Returns a resolved Path or raises PathSecurityError
"""

import os
import re
import urllib.parse
from pathlib import Path

from workspace.ids import validate_workspace_id


class PathSecurityError(ValueError):
    """Raised when a path violates workspace security boundaries."""
    pass


# ── Workspace root ──
ROOT = Path(__file__).resolve().parent.parent
WS_ROOT = ROOT / "workspaces"


# ── Patterns for traversal detection ──
_TRAVERSAL_PATTERNS = [
    # Literal ../
    re.compile(r"(^|[/\\])\.\."),
    # URL-encoded traversal: %2e%2e, %2E%2E, %2e%2E, etc.
    re.compile(r"(%[2Ff]%[2Ee]%[2Ee])", re.IGNORECASE),
    re.compile(r"(%[2Ee]{2}%[2Ff])", re.IGNORECASE),
    # Backslash traversal (Windows-style)
    re.compile(r"(^|[\\])\.\."),
    # Double URL encoding
    re.compile(r"%25[2Ff2Ee]"),
]

# ── Windows drive path pattern ──
_WIN_DRIVE = re.compile(r"^[A-Za-z]:[/\\]")


def _contains_traversal(subpath: str) -> bool:
    """Check if subpath contains path traversal attempts."""
    # Decode URL encoding first
    decoded = subpath
    try:
        decoded = urllib.parse.unquote(subpath)
    except Exception:
        pass  # If unquote fails, it's likely not a valid encoded path

    # Check raw and decoded
    for candidate in (subpath, decoded):
        # Windows drive path
        if _WIN_DRIVE.match(candidate):
            return True
        # Absolute path
        if candidate.startswith("/") or candidate.startswith("\\"):
            return True
        # Traversal patterns
        for pat in _TRAVERSAL_PATTERNS:
            if pat.search(candidate):
                return True

    return False


def safe_workspace_path(workspace_id: str, subpath: str = "") -> Path:
    """Validate and resolve a workspace file path securely.

    Blocks:
    - Path traversal (../, ..\\, encoded variants)
    - Absolute paths (/etc/passwd)
    - Windows drive paths (C:\\Windows)
    - Symlink escapes to outside workspace root
    - URL-encoded traversal (%2e%2e%2f)

    Args:
        workspace_id: Validated workspace identifier.
        subpath: Workspace-relative file path.

    Returns:
        Resolved absolute Path within the workspace.

    Raises:
        PathSecurityError on any security violation.
    """
    # ── 1. Validate workspace_id ──
    try:
        ws_id = validate_workspace_id(workspace_id)
    except ValueError as e:
        raise PathSecurityError(f"invalid_workspace_id: {e}") from e

    base = (WS_ROOT / ws_id).resolve()

    # ── 2. Check for traversal in raw subpath ──
    if _contains_traversal(subpath):
        raise PathSecurityError(f"path_escape_denied: traversal detected in '{subpath}'")

    # ── 3. Normalize: remove leading slashes, collapse redundant separators ──
    clean = subpath.lstrip("/").lstrip("\\")
    # Normalize path separators to OS-native
    clean = clean.replace("\\", "/")
    # Collapse multiple slashes
    clean = re.sub(r"/{2,}", "/", clean)

    # ── 4. Re-check after normalization ──
    if clean != subpath.lstrip("/").lstrip("\\") and _contains_traversal(clean):
        raise PathSecurityError(f"path_escape_denied: traversal after normalization in '{subpath}'")

    # ── 5. Resolve and check boundaries ──
    target = (base / clean).resolve()

    # Check prefix containment (string-based)
    base_str = str(base)
    target_str = str(target)

    if not target_str.startswith(base_str):
        raise PathSecurityError(
            f"path_escape_denied: '{subpath}' resolves outside workspace '{base_str}'"
        )

    # ── 6. Symlink check: verify real path is also contained ──
    try:
        if target.exists() or target.is_symlink():
            real_target = target.resolve()
            if not str(real_target).startswith(base_str):
                raise PathSecurityError(
                    f"path_escape_denied: symlink '{subpath}' points outside workspace"
                )
        # For non-existent paths: verify parent's real path
        else:
            parent = target.parent
            while parent != base:
                if parent.exists() or parent.is_symlink():
                    real_parent = parent.resolve()
                    if not str(real_parent).startswith(base_str):
                        raise PathSecurityError(
                            f"path_escape_denied: parent symlink '{subpath}' points outside workspace"
                        )
                    break
                parent = parent.parent
    except (OSError, RuntimeError) as e:
        raise PathSecurityError(f"invalid_workspace_path: {e}") from e

    return target


# ── Backward-compatible wrapper ──
def _validate_workspace_path(workspace_id: str, subpath: str = "") -> Path:
    """Backward-compatible wrapper around safe_workspace_path.

    Preserves ValueError behavior for existing callers.
    """
    try:
        return safe_workspace_path(workspace_id, subpath)
    except PathSecurityError as e:
        raise ValueError(str(e)) from e
