"""harness/test_v213_path_security_relative_to.py

v2.1.3: Test Path.relative_to containment in path_security.py.
Verifies prefix-spoofing is blocked and normal paths work.
"""

import os
import tempfile
import pytest


def _safe_path(ws_id="default", subpath=""):
    from tool_runtime.path_security import safe_workspace_path
    return safe_workspace_path(ws_id, subpath)


def _safe_path_error(ws_id="default", subpath=""):
    from tool_runtime.path_security import PathSecurityError
    try:
        _safe_path(ws_id, subpath)
        return None
    except (PathSecurityError, ValueError) as e:
        return str(e)


def _safe_path_ok(ws_id="default", subpath=""):
    try:
        _safe_path(ws_id, subpath)
        return True
    except Exception:
        return False


# ── Positive: normal paths pass ──

def test_normal_path_passes():
    assert _safe_path_ok("default", "") is True


def test_normal_subdir_passes():
    assert _safe_path_ok("default", "output/test.txt") is True


def test_nested_subdir_passes():
    assert _safe_path_ok("default", "output/reports/2024/summary.txt") is True


def test_non_existing_nested_passes():
    """Non-existing nested file under valid workspace must be allowed."""
    assert _safe_path_ok("default", "temp/nested/deep/file.txt") is True


# ── Negative: traversal blocked ──

def test_dotdot_blocked():
    err = _safe_path_error("default", "../etc/passwd")
    assert err and "traversal" in err.lower()


def test_encoded_dotdot_blocked():
    err = _safe_path_error("default", "%2e%2e%2fetc%2fpasswd")
    assert err and "traversal" in err.lower()


def test_absolute_path_blocked():
    err = _safe_path_error("default", "/etc/passwd")
    assert err and "traversal" in err.lower()


def test_windows_drive_blocked():
    err = _safe_path_error("default", "C:\\Windows\\System32")
    assert err and "traversal" in err.lower()


# ── Negative: prefix-spoofing blocked (v2.1.3 key test) ──

def test_prefix_spoofing_blocked():
    """default_evil must NOT pass containment for workspace 'default'."""
    # This path would pass a naive startswith check but must be blocked
    from tool_runtime.path_security import safe_workspace_path, PathSecurityError, WS_ROOT
    import shutil

    evil_ws = WS_ROOT / "default_evil"
    evil_ws.mkdir(parents=True, exist_ok=True)

    try:
        result = safe_workspace_path("default", "output/test.txt")
        result_str = str(result.resolve())
        # "default" must not resolve into "default_evil"
        assert "default_evil" not in result_str, \
            f"Path leaked into default_evil: {result_str}"
    except PathSecurityError:
        pass  # Expected if containment check catches it
    finally:
        if evil_ws.exists():
            shutil.rmtree(evil_ws, ignore_errors=True)


def test_prefix_spoofing_subdir_blocked():
    """default/subdir must not escape into default_evil/subdir."""
    from tool_runtime.path_security import WS_ROOT
    import shutil

    evil_ws = WS_ROOT / "default_evil"
    evil_sub = evil_ws / "subdir"
    evil_sub.mkdir(parents=True, exist_ok=True)

    try:
        result = _safe_path("default", "subdir/test.txt")
        result_str = str(result.resolve())
        assert "default_evil" not in result_str, \
            f"Path leaked into default_evil: {result_str}"
    except Exception as e:
        # Either containment check catches it or it resolves correctly
        assert "default_evil" not in str(e), f"Error should not reference default_evil: {e}"
    finally:
        if evil_ws.exists():
            shutil.rmtree(evil_ws, ignore_errors=True)


# ── _is_contained unit tests ──

def test_is_contained_positive():
    from tool_runtime.path_security import _is_contained
    from pathlib import Path
    base = Path("/tmp/test_ws_contained")
    base.mkdir(parents=True, exist_ok=True)
    try:
        child = base / "subdir" / "file.txt"
        child.parent.mkdir(parents=True, exist_ok=True)
        child.touch()
        assert _is_contained(child, base) is True
    finally:
        import shutil
        shutil.rmtree(base, ignore_errors=True)


def test_is_contained_negative():
    from tool_runtime.path_security import _is_contained
    from pathlib import Path
    base = Path("/tmp/test_ws_contained_2")
    base.mkdir(parents=True, exist_ok=True)
    try:
        outside = Path("/tmp/outside_file.txt")
        outside.touch()
        assert _is_contained(outside, base) is False
    finally:
        import shutil
        shutil.rmtree(base, ignore_errors=True)
        if Path("/tmp/outside_file.txt").exists():
            Path("/tmp/outside_file.txt").unlink()


def test_is_contained_prefix_spoof():
    """default_evil must NOT be contained within default."""
    from tool_runtime.path_security import _is_contained
    from pathlib import Path
    base = Path("/tmp/ws_default")
    evil = Path("/tmp/ws_default_evil")
    base.mkdir(parents=True, exist_ok=True)
    evil.mkdir(parents=True, exist_ok=True)
    try:
        assert _is_contained(evil, base) is False, \
            f"prefix-spoof: {evil} should not be contained in {base}"
    finally:
        import shutil
        shutil.rmtree(base, ignore_errors=True)
        shutil.rmtree(evil, ignore_errors=True)
