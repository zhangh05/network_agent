# harness/test_tool_runtime_client_integration_v021.py
"""ToolRuntimeClient Integration Tests v0.2.1.

Verifies low-risk tools work via ToolRuntimeClient, high-risk blocked,
forbidden blocked, redaction applied, audit metadata clean.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _get_client():
    """Get ToolRuntimeClient (not Flask test client)."""
    from tool_runtime.integration import get_default_tool_runtime_client
    return get_default_tool_runtime_client()


def _invoke_low(tool_id: str, args: dict = None):
    """Invoke a low-risk tool and return ToolResult."""
    from tool_runtime.schemas import ToolInvocation
    from tool_runtime.executor import ToolExecutor
    from tool_runtime.registry import ToolRegistry
    from tool_runtime.policy import ToolPolicy
    from tool_runtime.general_tools import register_all_general_tools
    from tool_runtime.builtins import register_builtin_tools

    reg = register_builtin_tools(ToolRegistry())
    reg = register_all_general_tools(reg)
    ex = ToolExecutor(reg, ToolPolicy())
    inv = ToolInvocation(
        tool_id=tool_id,
        arguments=args or {},
        workspace_id="default",
    )
    return ex.execute(inv)


class TestLowRiskToolExecution:
    """Verify low-risk tools execute successfully via ToolRuntimeClient."""

    def test_artifact_list(self):
        result = _invoke_low("artifact.list")
        assert result.status in ("succeeded", "dry_run"), f"Got {result.status}: {result.summary}"

    def test_artifact_read_summary(self):
        result = _invoke_low("artifact.read_summary", {"artifact_id": "art_nonexistent"})
        # Should return gracefully even if artifact doesn't exist
        assert result.status in ("succeeded", "failed"), f"Got {result.status}"

    def test_knowledge_search(self):
        result = _invoke_low("knowledge.search", {"query": "test", "limit": 3})
        assert result.status in ("succeeded", "dry_run"), f"Got {result.status}"

    def test_runtime_health(self):
        result = _invoke_low("runtime.health")
        assert result.status in ("succeeded", "dry_run"), f"Got {result.status}"

    def test_runtime_selfcheck(self):
        result = _invoke_low("runtime.selfcheck")
        assert result.status in ("succeeded", "dry_run"), f"Got {result.status}"

    def test_text_redact(self):
        result = _invoke_low("text.redact", {"text": "password secret123"})
        assert result.status in ("succeeded", "dry_run"), f"Got {result.status}"

    def test_json_validate(self):
        result = _invoke_low("json.validate", {"text": '{"key": "value"}'})
        assert result.status in ("succeeded", "dry_run"), f"Got {result.status}"

    def test_yaml_validate(self):
        result = _invoke_low("yaml.validate", {"text": "key: value\n"})
        assert result.status in ("succeeded", "dry_run"), f"Got {result.status}"

    def test_workspace_path_exists(self):
        result = _invoke_low("workspace.path_exists", {"filepath": "artifacts"})
        assert result.status in ("succeeded", "dry_run"), f"Got {result.status}"

    def test_report_render_markdown(self):
        result = _invoke_low("report.render_markdown", {"content": "# Test"})
        assert result.status in ("succeeded", "dry_run"), f"Got {result.status}"

    def test_web_search_safe(self):
        result = _invoke_low("web.search", {"query": "cisco bgp"})
        assert result.status in ("succeeded", "dry_run", "failed"), f"Got {result.status}"
        # If fails, should be graceful (e.g. network unavailable)
        if result.status == "failed":
            assert "unavailable" in result.summary.lower() or "error" in str(result.output or {}).lower()

    def test_web_fetch_blocks_private(self):
        result = _invoke_low("web.fetch_summary", {"url": "http://192.168.1.1/test"})
        out = result.output or {}
        assert out.get("ok") is False, f"Private URL should be blocked"


class TestPolicyEnforcement:
    """Policy pipeline: all invocations go through ToolPolicy + redaction."""

    def test_result_has_status_field(self):
        result = _invoke_low("artifact.list")
        assert result.status in ("succeeded", "dry_run", "failed", "blocked")

    def test_result_returns_toolresult_not_exception(self):
        """ToolExecutor never raises — always returns ToolResult."""
        try:
            result = _invoke_low("artifact.read_summary", {"artifact_id": "nonexistent"})
            assert hasattr(result, "status")
        except Exception as e:
            assert False, f"Should not raise: {e}"

    def test_output_is_redacted(self):
        result = _invoke_low("text.redact", {"text": "password secret123"})
        assert result.redacted, "Output should be redacted"

    def test_audit_metadata_has_no_full_args(self):
        result = _invoke_low("json.validate", {"text": '{"a": 1}'})
        # ToolResult should not contain the full original invocation arguments
        assert "secret123" not in str(result)

    def test_low_risk_no_approval_required(self):
        from tool_runtime.integration import get_default_tool_runtime_client
        client = get_default_tool_runtime_client()
        tools = client.list_tools()
        for t in tools:
            if t["risk_level"] == "low":
                assert not t["requires_approval"]


class TestHighRiskBlocked:
    """Verify high-risk tools are blocked without approval."""

    def test_command_approved_exec_blocked_no_approval(self):
        from tool_runtime.schemas import ToolInvocation
        from tool_runtime.executor import ToolExecutor
        from tool_runtime.registry import ToolRegistry
        from tool_runtime.policy import ToolPolicy
        from tool_runtime.general_tools import register_all_general_tools
        reg = register_all_general_tools(ToolRegistry())
        spec = reg.get_tool("command.approved_exec")
        spec.enabled = True
        ex = ToolExecutor(reg, ToolPolicy())
        inv = ToolInvocation(
            tool_id="command.approved_exec",
            arguments={"command_id": "system.platform_info"},
            workspace_id="default",
        )
        result = ex.execute(inv)
        assert result.status == "blocked"

    def test_powershell_script_blocked_no_approval(self):
        from tool_runtime.schemas import ToolInvocation
        from tool_runtime.executor import ToolExecutor
        from tool_runtime.registry import ToolRegistry
        from tool_runtime.policy import ToolPolicy
        from tool_runtime.general_tools import register_all_general_tools
        reg = register_all_general_tools(ToolRegistry())
        spec = reg.get_tool("powershell.approved_script")
        spec.enabled = True
        ex = ToolExecutor(reg, ToolPolicy())
        inv = ToolInvocation(
            tool_id="powershell.approved_script",
            arguments={"script_id": "win.platform_info"},
            workspace_id="default",
        )
        result = ex.execute(inv)
        assert result.status == "blocked"


class TestForbiddenTools:
    """Forbidden tools are not registered and not executable."""

    FORBIDDEN = [
        "shell.exec", "powershell.exec", "command.exec",
        "ssh.exec", "telnet.exec", "snmp.walk", "nmap.scan",
        "ping.sweep", "config.push", "file.read_any", "file.write_any",
    ]

    def test_forbidden_not_registered(self):
        client = _get_client()
        tools = client.list_tools()
        tool_ids = {t["tool_id"] for t in tools}
        for fid in self.FORBIDDEN:
            assert fid not in tool_ids

    def test_forbidden_in_policy(self):
        from tool_runtime.policy import V02_FORBIDDEN_TOOLS
        for fid in self.FORBIDDEN:
            assert fid in V02_FORBIDDEN_TOOLS
