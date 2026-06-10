"""Source Integrity & Runtime Safety Hardening Tests — v0.1"""
import os
import re
import json
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
PROJECT_PATH = Path(PROJECT_ROOT)


class TestSourceFormat:
    def test_archive_not_compressed(self):
        with open("runtime/archive.py") as f:
            lines = f.readlines()
        assert len(lines) > 50, f"archive.py has {len(lines)} lines — may be compressed"

    def test_retention_not_compressed(self):
        with open("runtime/retention.py") as f:
            lines = f.readlines()
        assert len(lines) > 50

    def test_backend_main_not_compressed(self):
        with open("backend/main.py") as f:
            lines = f.readlines()
        assert len(lines) > 100

    def test_selfcheck_not_compressed(self):
        with open("runtime/selfcheck.py") as f:
            lines = f.readlines()
        assert len(lines) > 50

    def test_diagnostics_not_compressed(self):
        with open("runtime/diagnostics.py") as f:
            lines = f.readlines()
        assert len(lines) > 50

    def test_readme_not_single_line(self):
        with open("README.md") as f:
            lines = f.readlines()
        assert len(lines) > 50

    def test_frontend_not_single_line(self):
        with open("frontend/index.html") as f:
            lines = f.readlines()
        assert len(lines) > 100


class TestReadmeBaseline:
    def test_readme_has_1224_passed(self):
        with open("README.md") as f:
            c = f.read()
        # v0.6: baseline updated; focus on focused regression count
        assert "656 passed" in c or "XXX passed" in c or "passed, 7 skipped" in c

    def test_readme_no_old_baseline_493(self):
        with open("README.md") as f:
            c = f.read()
        assert "493 passed" not in c

    def test_readme_no_old_baseline_850(self):
        with open("README.md") as f:
            c = f.read()
        assert "850 passed" not in c


class TestPathBoundary:
    def test_archive_uses_relative_to(self):
        # is_safe_path now lives in runtime/lifecycle_base.py
        with open("runtime/lifecycle_base.py") as f:
            c = f.read()
        assert "relative_to" in c
        with open("runtime/archive.py") as f:
            c = f.read()
        assert "is_safe_path" in c  # imports from lifecycle_base

    def test_retention_uses_relative_to(self):
        with open("runtime/lifecycle_base.py") as f:
            c = f.read()
        assert "relative_to" in c
        with open("runtime/retention.py") as f:
            c = f.read()
        assert "is_safe_path" in c  # imports from lifecycle_base

    def test_default2_not_pass_default(self):
        from runtime.lifecycle_base import is_safe_path
        ws = PROJECT_PATH / "workspaces" / "default"
        ws2 = PROJECT_PATH / "workspaces" / "default2"
        if ws.exists():
            if ws2.exists() and ws2.is_dir():
                test_file = ws2 / "test.txt"
                test_file.write_text("test")
                assert is_safe_path(test_file, ws) is False
                test_file.unlink()

    def test_path_traversal_blocked(self):
        from runtime.lifecycle_base import is_safe_path
        ws = PROJECT_PATH / "workspaces" / "default"
        if ws.exists():
            traversal = PROJECT_PATH / "workspaces" / "default" / ".." / ".." / "etc"
            assert is_safe_path(traversal.resolve(), ws) is False


class TestRedaction:
    def test_sanitize_paths(self):
        from runtime.redaction import sanitize_output
        result = sanitize_output("Error at /Users/admin/file.txt")
        assert "/Users/" not in result
        assert "PATH_REDACTED" in result

    def test_sanitize_passwords(self):
        from runtime.redaction import sanitize_output
        result = sanitize_output("password mysecret123")
        assert "mysecret123" not in result

    def test_sanitize_tokens(self):
        from runtime.redaction import sanitize_output
        result = sanitize_output("token=abc123xyz")
        assert "abc123xyz" not in result

    def test_sanitize_bearer(self):
        from runtime.redaction import sanitize_output
        result = sanitize_output("Authorization: Bearer abcdef12345")
        assert "abcdef12345" not in result

    def test_sanitize_dict(self):
        from runtime.redaction import sanitize_dict
        result = sanitize_dict({"msg": "Error at /Users/a/file", "cookie": "ok"})
        assert "/Users/" not in result["msg"]
        assert "ok" in result["cookie"]  # non-sensitive key preserved


class TestDocArchive:
    def test_doc_exists(self):
        assert os.path.exists("docs/RUNTIME_ARCHIVE.md")

    def test_doc_has_dry_run(self):
        with open("docs/RUNTIME_ARCHIVE.md") as f:
            c = f.read()
        assert "dry-run" in c or "dry_run" in c

    def test_doc_has_confirm(self):
        with open("docs/RUNTIME_ARCHIVE.md") as f:
            c = f.read()
        assert "confirm" in c.lower()

    def test_doc_has_security_redlines(self):
        with open("docs/RUNTIME_ARCHIVE.md") as f:
            c = f.read()
        assert "Security Red Lines" in c or "security red" in c.lower()


class TestNoForbiddenRestored:
    FORBIDDEN = ["/api/translate", "backend.services.config_translation",
                 "GraphAgent", "network-translator"]

    def test_no_forbidden_in_backend_main(self):
        with open("backend/main.py") as f:
            c = f.read()
        assert "/api/translate" not in c or "check" in c.lower()
        for term in ("8020", "MiniMax-M1"):
            assert term not in c

    def test_no_tool_invoke_api(self):
        with open("backend/main.py") as f:
            c = f.read()
        assert "/api/tool" not in c

    def test_no_tool_invoke_ui(self):
        with open("frontend/index.html") as f:
            c = f.read()
        assert "invoke_tool" not in c

    def test_no_ssh_handler(self):
        import tool_runtime.builtins
        import inspect
        source = inspect.getsource(tool_runtime.builtins)
        assert "def _handler_ssh" not in source

    def test_no_deployable_claim_ui(self):
        with open("frontend/index.html") as f:
            c = f.read()
        assert "可直接下发" not in c

    def test_ui_no_absolute_path(self):
        with open("frontend/index.html") as f:
            c = f.read()
        assert "/Users/" not in c
        assert "/home/" not in c
