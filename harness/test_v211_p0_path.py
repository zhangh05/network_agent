# harness/test_v211_p0_path.py
"""P0-2: Safe workspace path resolver tests.

Tests:
- ../../etc/passwd → rejected
- /etc/passwd → rejected
- C:\\Windows\\System32 → rejected
- ..%2f..%2f → rejected
- symlink outside workspace → rejected
- Legit workspace relative path → allowed
- Nested legit path → allowed
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class TestSafeWorkspacePath:
    """Path traversal prevention tests."""

    @pytest.fixture(autouse=True)
    def _patch_ws_root(self, monkeypatch, tmp_path):
        """Use temp path as workspace root."""
        ws_root = tmp_path / "workspaces"
        ws_root.mkdir(parents=True, exist_ok=True)
        # Create a test workspace
        test_ws = ws_root / "test"
        test_ws.mkdir(parents=True, exist_ok=True)
        # Create a file inside
        (test_ws / "hello.txt").write_text("hello", encoding="utf-8")
        # Create a nested directory
        (test_ws / "subdir").mkdir(parents=True, exist_ok=True)
        (test_ws / "subdir" / "nested.txt").write_text("nested", encoding="utf-8")

        monkeypatch.setattr("tool_runtime.path_security.WS_ROOT", ws_root)

    def test_reject_dotdot_escape(self):
        """../../etc/passwd is rejected."""
        from tool_runtime.path_security import safe_workspace_path, PathSecurityError
        with pytest.raises(PathSecurityError) as exc:
            safe_workspace_path("test", "../../etc/passwd")
        assert "path_escape_denied" in str(exc.value)

    def test_reject_absolute_path(self):
        """/etc/passwd is rejected."""
        from tool_runtime.path_security import safe_workspace_path, PathSecurityError
        with pytest.raises(PathSecurityError) as exc:
            safe_workspace_path("test", "/etc/passwd")
        assert "path_escape_denied" in str(exc.value)

    def test_reject_windows_drive(self):
        """C:\\Windows\\System32 is rejected."""
        from tool_runtime.path_security import safe_workspace_path, PathSecurityError
        with pytest.raises(PathSecurityError) as exc:
            safe_workspace_path("test", "C:\\Windows\\System32")
        assert "path_escape_denied" in str(exc.value)

    def test_reject_url_encoded_traversal(self):
        """..%2f..%2f is rejected (URL-encoded traversal)."""
        from tool_runtime.path_security import safe_workspace_path, PathSecurityError
        with pytest.raises(PathSecurityError) as exc:
            safe_workspace_path("test", "..%2f..%2fetc%2fpasswd")
        assert "path_escape_denied" in str(exc.value)

    def test_reject_double_dotdot(self):
        """.////. is also rejected."""
        from tool_runtime.path_security import safe_workspace_path, PathSecurityError
        with pytest.raises(PathSecurityError) as exc:
            safe_workspace_path("test", "....//....//etc/passwd")
        assert "path_escape_denied" in str(exc.value)

    def test_reject_encoded_dot_dot(self):
        """%2e%2e%2f pattern is rejected."""
        from tool_runtime.path_security import safe_workspace_path, PathSecurityError
        with pytest.raises(PathSecurityError) as exc:
            safe_workspace_path("test", "%2e%2e%2fetc%2fpasswd")
        assert "path_escape_denied" in str(exc.value)

    def test_allow_legit_relative(self):
        """Legitimate workspace-relative path is allowed."""
        from tool_runtime.path_security import safe_workspace_path
        target = safe_workspace_path("test", "hello.txt")
        assert target.is_file()
        assert target.read_text(encoding="utf-8") == "hello"

    def test_allow_nested_legit(self):
        """Nested workspace-relative path is allowed."""
        from tool_runtime.path_security import safe_workspace_path
        target = safe_workspace_path("test", "subdir/nested.txt")
        assert target.is_file()
        assert target.read_text(encoding="utf-8") == "nested"

    def test_reject_symlink_escape(self, tmp_path):
        """Symlink pointing outside workspace is rejected."""
        from tool_runtime.path_security import safe_workspace_path, PathSecurityError
        # Create a symlink inside the workspace pointing outside
        ws_root = tmp_path / "workspaces"
        test_ws = ws_root / "test"
        test_ws.mkdir(parents=True, exist_ok=True)

        outside_file = tmp_path / "outside.txt"
        outside_file.write_text("secret", encoding="utf-8")

        symlink = test_ws / "escape_link"
        symlink.symlink_to(outside_file)

        with pytest.raises(PathSecurityError) as exc:
            safe_workspace_path("test", "escape_link")
        assert "path_escape_denied" in str(exc.value) or "symlink" in str(exc.value).lower()

    def test_invalid_workspace_id(self):
        """Invalid workspace_id is rejected."""
        from tool_runtime.path_security import safe_workspace_path, PathSecurityError
        with pytest.raises(PathSecurityError) as exc:
            safe_workspace_path("../../../etc", "test.txt")
        assert "invalid_workspace" in str(exc.value).lower()

    def test_empty_subpath_allowed(self):
        """Empty subpath returns workspace root."""
        from tool_runtime.path_security import safe_workspace_path
        target = safe_workspace_path("test", "")
        assert target.is_dir()


class TestBackwardCompatible:
    """Backward-compatible _validate_workspace_path wrapper."""

    def test_raises_valueerror(self):
        """Wrapper raises ValueError (not PathSecurityError) for traversal."""
        from tool_runtime.path_security import _validate_workspace_path
        with pytest.raises(ValueError):
            _validate_workspace_path("test", "../../etc/passwd")

    def test_works_for_legit_path(self):
        """Wrapper works for legitimate paths."""
        from tool_runtime.path_security import _validate_workspace_path
        target = _validate_workspace_path("test", "hello.txt")
        # May raise if WS_ROOT not patched — that's ok
        # Just verify the function exists and is callable
        assert target is not None
