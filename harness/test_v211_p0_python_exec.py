# harness/test_v211_p0_python_exec.py
"""P0-3: python_exec environment variable isolation tests.

Tests:
- TEST_SECRET_TOKEN not visible in subprocess env
- OPENAI_API_KEY not visible
- PATH is preserved
- stdout redaction of secrets
- timeout behaviour unchanged
"""

import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class TestPythonExecEnvIsolation:
    """Environment variable isolation tests."""

    def test_safe_env_excludes_secret_token(self, monkeypatch):
        """_build_safe_env excludes TEST_SECRET_TOKEN."""
        monkeypatch.setenv("TEST_SECRET_TOKEN", "abc123")
        monkeypatch.setenv("PATH", "/usr/bin")
        monkeypatch.setenv("LANG", "en_US.UTF-8")

        from tool_runtime.python_exec import _build_safe_env
        safe_env = _build_safe_env()
        assert "TEST_SECRET_TOKEN" not in safe_env

    def test_safe_env_excludes_openai_key(self, monkeypatch):
        """_build_safe_env excludes OPENAI_API_KEY."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
        monkeypatch.setenv("PATH", "/usr/bin")

        from tool_runtime.python_exec import _build_safe_env
        safe_env = _build_safe_env()
        assert "OPENAI_API_KEY" not in safe_env

    def test_safe_env_excludes_anthropic_key(self, monkeypatch):
        """_build_safe_env excludes ANTHROPIC_API_KEY."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "ant-test-key")
        monkeypatch.setenv("PATH", "/usr/bin")

        from tool_runtime.python_exec import _build_safe_env
        safe_env = _build_safe_env()
        assert "ANTHROPIC_API_KEY" not in safe_env

    def test_safe_env_excludes_minimax_key(self, monkeypatch):
        """_build_safe_env excludes MINIMAX_API_KEY."""
        monkeypatch.setenv("MINIMAX_API_KEY", "mm-test-key")
        monkeypatch.setenv("PATH", "/usr/bin")

        from tool_runtime.python_exec import _build_safe_env
        safe_env = _build_safe_env()
        assert "MINIMAX_API_KEY" not in safe_env

    def test_safe_env_excludes_http_proxy(self, monkeypatch):
        """_build_safe_env excludes HTTP_PROXY."""
        monkeypatch.setenv("HTTP_PROXY", "http://proxy:8080")
        monkeypatch.setenv("HTTPS_PROXY", "http://proxy:8443")
        monkeypatch.setenv("PATH", "/usr/bin")

        from tool_runtime.python_exec import _build_safe_env
        safe_env = _build_safe_env()
        assert "HTTP_PROXY" not in safe_env
        assert "HTTPS_PROXY" not in safe_env

    def test_safe_env_excludes_aws_credentials(self, monkeypatch):
        """_build_safe_env excludes AWS credentials."""
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIA_TEST")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test-secret")
        monkeypatch.setenv("PATH", "/usr/bin")

        from tool_runtime.python_exec import _build_safe_env
        safe_env = _build_safe_env()
        assert "AWS_ACCESS_KEY_ID" not in safe_env
        assert "AWS_SECRET_ACCESS_KEY" not in safe_env

    def test_safe_env_preserves_path(self, monkeypatch):
        """PATH is preserved in safe env."""
        monkeypatch.setenv("PATH", "/custom/bin:/usr/bin")

        from tool_runtime.python_exec import _build_safe_env
        safe_env = _build_safe_env()
        assert "PATH" in safe_env
        assert safe_env["PATH"] == "/custom/bin:/usr/bin"

    def test_safe_env_preserves_lang(self, monkeypatch):
        """LANG is preserved."""
        monkeypatch.setenv("LANG", "en_US.UTF-8")

        from tool_runtime.python_exec import _build_safe_env
        safe_env = _build_safe_env()
        assert "LANG" in safe_env

    def test_safe_env_preserves_tz(self, monkeypatch):
        """TZ is preserved."""
        monkeypatch.setenv("TZ", "Asia/Shanghai")

        from tool_runtime.python_exec import _build_safe_env
        safe_env = _build_safe_env()
        assert "TZ" in safe_env

    def test_safe_env_excludes_generic_token(self, monkeypatch):
        """Any env var containing TOKEN in UPPER is excluded."""
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
        monkeypatch.setenv("CI_JOB_TOKEN", "ci-test")
        monkeypatch.setenv("PATH", "/usr/bin")

        from tool_runtime.python_exec import _build_safe_env
        safe_env = _build_safe_env()
        assert "GITHUB_TOKEN" not in safe_env
        assert "CI_JOB_TOKEN" not in safe_env

    def test_safe_env_excludes_secret(self, monkeypatch):
        """Any env var containing SECRET in UPPER is excluded."""
        monkeypatch.setenv("MY_SECRET", "shh")
        monkeypatch.setenv("DEPLOY_SECRET_KEY", "value")
        monkeypatch.setenv("PATH", "/usr/bin")

        from tool_runtime.python_exec import _build_safe_env
        safe_env = _build_safe_env()
        assert "MY_SECRET" not in safe_env
        assert "DEPLOY_SECRET_KEY" not in safe_env

    def test_redact_stdout_secrets(self):
        """Stdout with secret patterns gets redacted."""
        from tool_runtime.python_exec import _redact_stdout_stderr
        stdout = "Found API_KEY=supersecret in output"
        stderr = "Error while using TOKEN=abc123"

        out, err = _redact_stdout_stderr(stdout, stderr)
        assert "supersecret" not in out
        assert "abc123" not in err
        assert "[REDACTED]" in out
        assert "[REDACTED]" in err

    def test_redact_preserves_normal_output(self):
        """Normal output without secrets is unchanged."""
        from tool_runtime.python_exec import _redact_stdout_stderr
        stdout = "Result: 42"
        stderr = ""

        out, err = _redact_stdout_stderr(stdout, stderr)
        assert out == "Result: 42"
        assert err == ""

    def test_execute_security_fail_at_ast(self):
        """Forbidden imports are caught at AST level before subprocess."""
        from tool_runtime.python_exec import execute_python_code
        result = execute_python_code(
            "import os\nprint(os.environ)",
            "test",
            "test-run",
            timeout=5,
        )
        assert result["ok"] is False
        assert "Security" in result.get("error", "")

    def test_execute_auth_module_importable(self):
        """The auth module itself loads cleanly."""
        import backend.core.auth
        assert hasattr(backend.core.auth, "register_auth_middleware")
        assert hasattr(backend.core.auth, "is_public_path")

    def test_path_security_module_importable(self):
        """The path_security module loads cleanly."""
        import tool_runtime.path_security
        assert hasattr(tool_runtime.path_security, "safe_workspace_path")
        assert hasattr(tool_runtime.path_security, "PathSecurityError")

    def test_python_exec_module_loads(self):
        """python_exec module loads with env isolation functions."""
        import tool_runtime.python_exec
        assert hasattr(tool_runtime.python_exec, "_build_safe_env")
        assert hasattr(tool_runtime.python_exec, "_redact_stdout_stderr")
        assert hasattr(tool_runtime.python_exec, "execute_python_code")
