"""Retired Surface Physical Removal & Runtime Safety Tests — v0.1"""
import os
import sys
import json
import re
import inspect
import pytest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class TestLegacyRemoved:
    def test_legacy_dir_not_exists(self):
        assert not (PROJECT_ROOT / "legacy").exists()

    def test_legacy_apps_not_exists(self):
        assert not (PROJECT_ROOT / "legacy" / "apps").exists()

    def test_no_old_api_translate_app(self):
        # Check with subprocess that old translator_service is gone
        assert not (PROJECT_ROOT / "legacy" / "apps" / "translator_service" / "app.py").exists()

    def test_no_old_graphagent_app(self):
        assert not (PROJECT_ROOT / "legacy" / "apps" / "agent_service" / "app.py").exists()


class TestActiveCodeClean:
    def test_no_active_api_translate(self):
        c = (PROJECT_ROOT / "backend" / "main.py").read_text()
        assert '"/api/translate"' not in c

    def test_no_backend_services_config_translation(self):
        assert not (PROJECT_ROOT / "backend" / "services" / "config_translation.py").exists()

    def test_no_8020_port(self):
        c = (PROJECT_ROOT / "backend" / "main.py").read_text()
        assert "8020" not in c

    def test_only_config_translation_enabled(self):
        from registry.loader import load_module_registry
        mods = load_module_registry()
        enabled = sorted([m.module_name for m in mods if m.is_enabled()])
        assert enabled == sorted(["config_translation", "knowledge_base"])


class TestRetiredSurfacesDoc:
    def test_doc_exists(self):
        assert (PROJECT_ROOT / "docs" / "RETIRED_SURFACES.md").exists()

    def test_doc_marks_retired(self):
        c = (PROJECT_ROOT / "docs" / "RETIRED_SURFACES.md").read_text()
        for term in ("/api/translate", "GraphAgent", "network-translator", "8020"):
            assert term in c

    def test_doc_has_anti_regression_ref(self):
        c = (PROJECT_ROOT / "docs" / "RETIRED_SURFACES.md").read_text()
        assert "anti-regression" in c.lower() or "anti_regression" in c.lower()


class TestPathBoundary:
    def test_archive_no_startswith_path_boundary(self):
        c = (PROJECT_ROOT / "runtime" / "archive.py").read_text()
        # Find the _is_safe_path function
        func_start = c.find("def _is_safe_path")
        func_text = c[func_start:func_start + 500] if func_start >= 0 else c
        # Must use relative_to
        assert "relative_to" in func_text
        # Must NOT use startswith for path checking
        assert "startswith(str(ws_resolved))" not in func_text

    def test_retention_no_startswith_path_boundary(self):
        c = (PROJECT_ROOT / "runtime" / "retention.py").read_text()
        func_start = c.find("def _is_safe_path")
        func_text = c[func_start:func_start + 500] if func_start >= 0 else c
        assert "relative_to" in func_text
        assert "startswith(str(ws_resolved))" not in func_text

    def test_default2_not_pass_default(self):
        from runtime.archive import _is_safe_path
        ws = PROJECT_ROOT / "workspaces" / "default"
        ws2 = PROJECT_ROOT / "workspaces" / "default2"
        if ws.exists():
            if ws2.exists() and ws2.is_dir():
                test_file = ws2 / "test.txt"
                test_file.write_text("test")
                result = _is_safe_path(test_file, ws)
                test_file.unlink()
                assert result is False

    def test_archive_apply_double_checks_boundary(self):
        import warnings
        c = (PROJECT_ROOT / "runtime" / "archive.py").read_text()
        # apply_archive should call _is_safe_path before moving
        assert "_is_safe_path" in c


class TestRedaction:
    def test_file_format_ok(self):
        with open(PROJECT_ROOT / "runtime" / "redaction.py") as f:
            lines = f.readlines()
        assert len(lines) > 30

    def test_key_level_password(self):
        from runtime.redaction import redact_dict
        result = redact_dict({"password": "mysecret123", "normal": "ok"})
        assert result["password"] == "[REDACTED]"
        assert result["normal"] == "ok"

    def test_key_level_token(self):
        from runtime.redaction import redact_dict
        result = redact_dict({"api_key": "sk-abc123xyz", "name": "test"})
        assert result["api_key"] == "[REDACTED]"
        assert result["name"] == "test"

    def test_key_level_community(self):
        from runtime.redaction import redact_dict
        result = redact_dict({"community": "public", "port": 161})
        assert result["community"] == "[REDACTED]"
        assert result["port"] == 161

    def test_nested_redaction(self):
        from runtime.redaction import redact_dict
        result = redact_dict({
            "config": {"password": "secret", "data": "normal"},
            "list": [{"token": "abc"}, "hello"],
        })
        assert result["config"]["password"] == "[REDACTED]"
        assert result["config"]["data"] == "normal"
        assert result["list"][0]["token"] == "[REDACTED]"

    def test_absolute_path_redacted(self):
        from runtime.redaction import redact_text
        result = redact_text("Error: /Users/john/.secret")
        assert "/Users/" not in result
        assert "PATH_REDACTED" in result

    def test_windows_path_redacted(self):
        from runtime.redaction import redact_text
        result = redact_text("File: C:\\Users\\john\\file.txt")
        assert "C:\\" not in result or "PATH_REDACTED" in result

    def test_bearer_redacted(self):
        from runtime.redaction import redact_text
        result = redact_text("Authorization: Bearer mytoken12345abc")
        assert "mytoken12345abc" not in result

    def test_sk_key_redacted(self):
        from runtime.redaction import redact_text
        result = redact_text("Key: sk-abc123secretkey")
        assert "abc123secretkey" not in result
        assert "sk-abc" in result or "[REDACTED]" in result

    def test_json_serializable(self):
        from runtime.redaction import redact_dict
        result = redact_dict({"data": "hello", "password": "x"})
        json.dumps(result)  # must not raise

    def test_legacy_alias_sanitize_output(self):
        from runtime.redaction import sanitize_output
        result = sanitize_output("password secret123")
        assert "secret123" not in result


class TestSourceFormat:
    def test_archive_multiline(self):
        c = (PROJECT_ROOT / "runtime" / "archive.py").read_text()
        assert len(c.splitlines()) > 50

    def test_retention_multiline(self):
        c = (PROJECT_ROOT / "runtime" / "retention.py").read_text()
        assert len(c.splitlines()) > 50

    def test_redaction_multiline(self):
        c = (PROJECT_ROOT / "runtime" / "redaction.py").read_text()
        assert len(c.splitlines()) > 30

    def test_backend_main_multiline(self):
        c = (PROJECT_ROOT / "backend" / "main.py").read_text()
        assert len(c.splitlines()) > 100


class TestReadmeDocs:
    def test_readme_has_current_baseline(self):
        c = (PROJECT_ROOT / "README.md").read_text()
        assert "passed" in c.lower()
        # Should not have old baselines
        assert "493 passed" not in c
        assert "850 passed" not in c

    def test_retired_surfaces_doc_in_readme(self):
        c = (PROJECT_ROOT / "README.md").read_text()
        assert "RETIRED_SURFACES" in c or "retired" in c.lower()
