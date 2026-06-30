"""Runtime shell safety and registry reload contract.

This test file pins current production behavior:

  1. bash subprocesses receive only an allowlisted environment.
  2. subprocess stdout/stderr are redacted before returning to LLM context.
  3. registry reload invalidates the derived tool catalog snapshot.
"""

import os
from pathlib import Path

import pytest

PROJECT_ROOT = Path("/Users/zhangh01/Desktop/network_agent")


def test_run_shell_blocks_api_keys_and_tokens():
    """``_build_safe_shell_env`` must NEVER inherit API_KEY / TOKEN /
    SECRET / PROXY / PASSWORD / CREDENTIAL / PRIVATE_KEY variants.

    We seed os.environ with a known sentinel value, call the helper,
    and assert the sentinel is absent from the result.
    """
    import sys
    sys.path.insert(0, str(PROJECT_ROOT))
    from tool_runtime.general_tools.command_tools import _build_safe_shell_env

    sentinels = {
        "OPENAI_API_KEY": "sk-sentinel-openai-1234567890abcdef",
        "NETWORK_AGENT_ADMIN_TOKEN": "admin-sentinel-987654321",
        "LLM_TOKEN": "llm-sentinel-abcdef",
        "PROXY_URL": "http://user:pass@proxy.example.com",
        "GITHUB_PASSWORD": "pw-sentinel-abcdef",
        "MY_PRIVATE_KEY": "key-sentinel-abcdef",
    }
    sentinel_backup = {k: os.environ.get(k) for k in sentinels}
    try:
        for k, v in sentinels.items():
            os.environ[k] = v
        env = _build_safe_shell_env()
        for k in sentinels:
            assert k not in env, (
                f"_build_safe_shell_env leaked sensitive var {k!r}: "
                f"value={env.get(k)!r}"
            )
    finally:
        for k, old in sentinel_backup.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old


def test_run_shell_preserves_posix_basics():
    """Linux allowlist must keep PATH/HOME/USER/LANG/TZ/PWD so the
    bash subprocess can resolve executables and resolve locales.
    """
    import sys
    sys.path.insert(0, str(PROJECT_ROOT))
    from tool_runtime.general_tools.command_tools import _build_safe_shell_env

    sentinels = {
        "PATH": "/usr/bin:/bin",
        "HOME": "/home/tester",
        "USER": "tester",
        "LANG": "en_US.UTF-8",
        "TZ": "UTC",
    }
    sentinel_backup = {k: os.environ.get(k) for k in sentinels}
    try:
        for k, v in sentinels.items():
            os.environ[k] = v
        env = _build_safe_shell_env()
        for k, v in sentinels.items():
            assert env.get(k) == v, (
                f"_build_safe_shell_env dropped POSIX-essential {k!r}; "
                f"expected {v!r}, got {env.get(k)!r}"
            )
    finally:
        for k, old in sentinel_backup.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old


def test_run_shell_redacts_subprocess_output():
    """_run_shell redacts the child process's stdout/stderr before
    returning — a command that intentionally ``echo $OPENAI_API_KEY``
    must NOT be echoed back to the LLM via the tool result.
    """
    import sys
    sys.path.insert(0, str(PROJECT_ROOT))

    # Force-set a sentinel before invoking _run_shell so the child
    # shell can see it via $OPENAI_API_KEY.
    sentinels = {
        "OPENAI_API_KEY": "sk-runshellsentinel-1234567890",
        "PATH": "/usr/bin:/bin",
        "HOME": "/tmp",
    }
    sentinel_backup = {k: os.environ.get(k) for k in sentinels}
    try:
        for k, v in sentinels.items():
            os.environ[k] = v
        # We use the bash native form 'echo "$OPENAI_API_KEY"' to avoid
        # bash's plugin-style variable expansion masking.
        from tool_runtime.general_tools.shared import _run_shell
        result = _run_shell('echo "$OPENAI_API_KEY"')
        assert result["ok"], f"shell exec failed: {result}"
        assert "sk-runshellsentinel" not in result["stdout"], (
            f"_run_shell leaked api_key into stdout: {result['stdout']!r}"
        )
    finally:
        for k, old in sentinel_backup.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old


def test_run_shell_redacts_before_truncating():
    """Redaction must happen before max-output truncation so a secret
    cannot be cut into an unredactable fragment at the boundary.
    """
    import sys
    sys.path.insert(0, str(PROJECT_ROOT))

    from tool_runtime.general_tools import shared
    src = Path(shared.__file__).read_text(encoding="utf-8")
    stdout_redact_idx = src.index('stdout = redact_tool_output(result.stdout or "")')
    stdout_truncate_idx = src.index('[:_SHELL_MAX_OUTPUT]', stdout_redact_idx)
    assert stdout_redact_idx < stdout_truncate_idx


def test_reload_all_invalidates_catalog_snapshot():
    """registry.reload_all() must clear the catalog snapshot LRU so
    /api/tools/catalog returns a fresh fingerprint after hot reload.
    """
    import sys
    sys.path.insert(0, str(PROJECT_ROOT))
    from tool_runtime.canonical_registry import CANONICAL_REGISTRY
    from tool_runtime.catalog_snapshot import (
        build_catalog_snapshot,
        reset_catalog_snapshot_cache,
    )
    import registry.loader as _rl

    # Restore-callback for the test's mutation
    original_keys = set(CANONICAL_REGISTRY.keys())
    try:
        reset_catalog_snapshot_cache()
        baseline = build_catalog_snapshot()
        baseline_count = baseline["count"]

        # Simulate a reload: insert a synthetic canonical entry that
        # is structurally identical to exec.run (ToolSpec exposes a
        # canonical_tool_id; the catalog enumerates from CANONICAL_REGISTRY).
        from tool_runtime.canonical_registry import CANONICAL_REGISTRY as _cr
        from tool_runtime.canonical_registry import CanonicalToolEntry
        # Use a tiny synthetic entry that satisfies the catalog loop;
        # ``build_catalog_snapshot`` only reads canonical_tool_id.
        exec_entry = _cr["exec.run"]
        _cr["test.reload_check"] = CanonicalToolEntry(
            canonical_tool_id="test.reload_check",
            handler=exec_entry.handler,
            input_schema=exec_entry.input_schema,
            description=exec_entry.description,
            risk_level=exec_entry.risk_level,
            requires_approval=exec_entry.requires_approval,
            permission_action=exec_entry.permission_action,
        )

        # Without reload_all, the snapshot is still cached at the old
        # count (this precondition validates that the cache IS sticky).
        stale = build_catalog_snapshot()
        assert stale["count"] == baseline_count, (
            f"sanity check failed: snapshot was not memoized; got {stale['count']}, "
            f"expected baseline {baseline_count}"
        )

        _rl.reload_all()
        fresh = build_catalog_snapshot()
        assert fresh["count"] == baseline_count + 1, (
            f"reload_all() did not invalidate the catalog snapshot cache; "
            f"got {fresh['count']} tools, expected {baseline_count + 1}"
        )
        assert fresh["catalog_fingerprint"] != baseline["catalog_fingerprint"]
    finally:
        # Always restore the registry to its production shape.
        for k in list(CANONICAL_REGISTRY.keys()):
            if k not in original_keys:
                del CANONICAL_REGISTRY[k]
        reset_catalog_snapshot_cache()
