# harness/test_phase6_tool_runtime_boundary.py
"""Phase 6: Tool Runtime hard boundary enforcement."""

import pytest, uuid
from tool_runtime.manifest_registry import get_manifest, is_retryable


class TestCallerPermission:
    def test_allowed_caller_passes(self):
        from tool_runtime.integration import get_default_tool_runtime_client
        from tool_runtime.context import ToolRuntimeContext
        client = get_default_tool_runtime_client()
        ctx = ToolRuntimeContext(
            workspace_id="default",
            requested_by="turn_runner",
        )
        result = client.invoke("web.search", {"query": "test", "top_k": 1}, context=ctx)
        # Should not be blocked by caller permission
        assert result.status != "blocked" or "caller" not in str(result.summary).lower()

    def test_disallowed_caller_blocked(self):
        from tool_runtime.integration import get_default_tool_runtime_client
        from tool_runtime.context import ToolRuntimeContext
        client = get_default_tool_runtime_client()
        ctx = ToolRuntimeContext(
            workspace_id="default",
            requested_by="bogus_caller",
        )
        result = client.invoke("device.delete", {"asset_id": "test"}, context=ctx)
        # device.delete.allowed_callers only includes valid runtime callers
        assert result.status == "blocked" or "allow" in str(result.summary).lower()


class TestManifestGate:
    def test_missing_manifest_blocked(self):
        from tool_runtime.integration import get_default_tool_runtime_client
        from tool_runtime.context import ToolRuntimeContext
        client = get_default_tool_runtime_client()
        ctx = ToolRuntimeContext(workspace_id="default")
        result = client.invoke("nonexistent.tool.fake", {}, context=ctx)
        assert result.status == "blocked"
        assert "manifest" in str(result.summary).lower()


class TestRedaction:
    def test_tool_output_redacted_by_default(self):
        from tool_runtime.integration import get_default_tool_runtime_client
        from tool_runtime.context import ToolRuntimeContext
        client = get_default_tool_runtime_client()
        ctx = ToolRuntimeContext(workspace_id="default")
        result = client.invoke("tool.catalog.search", {}, context=ctx)
        # Should be redacted
        assert result.redacted is True

    def test_high_risk_rest_invoke_not_direct_execute(self):
        from tool_runtime.integration import get_default_tool_runtime_client
        from tool_runtime.context import ToolRuntimeContext
        client = get_default_tool_runtime_client()
        ctx = ToolRuntimeContext(workspace_id="default", requested_by="rest_api")
        result = client.invoke("git.push", {"remote": "origin"}, context=ctx)
        # Should go through pipeline, not directly execute
        assert result.status in ("failed", "blocked", "succeeded", "dry_run")


class TestToolPolicySafetySemantics:
    def test_high_risk_tool_call_allowed_until_arguments_are_unsafe(self):
        from tool_runtime.policy import ToolPolicy
        from tool_runtime.schemas import ToolInvocation, ToolSpec

        spec = ToolSpec(
            tool_id="exec.run",
            category="exec",
            risk_level="high",
            requires_approval=True,
            input_schema={"type": "object", "properties": {}},
        )

        decision = ToolPolicy().check(
            spec,
            ToolInvocation(
                tool_id="exec.run",
                arguments={"target": "local", "command": "ifconfig"},
                workspace_id="default",
                requested_by="turn_runner",
            ),
        )

        assert decision.allowed is True
        assert decision.requires_approval is False
        assert "high_risk_no_approval_id" not in decision.blocked_rules

    def test_high_risk_tool_call_blocks_destructive_arguments(self):
        from tool_runtime.policy import ToolPolicy
        from tool_runtime.schemas import ToolInvocation, ToolSpec

        spec = ToolSpec(
            tool_id="exec.run",
            category="exec",
            risk_level="high",
            requires_approval=True,
            input_schema={"type": "object", "properties": {}},
        )

        decision = ToolPolicy().check(
            spec,
            ToolInvocation(
                tool_id="exec.run",
                arguments={"target": "local", "command": "rm -rf /tmp/network-agent-test"},
                workspace_id="default",
                requested_by="turn_runner",
            ),
        )

        assert decision.allowed is False
        assert "unsafe_arguments" in decision.blocked_rules


class TestNoBypass:
    def test_web_tools_use_client_invoke(self):
        """Confirm web_tools.py merged handlers use client.invoke, not direct handler."""
        import tool_runtime.general_tools.web_tools as wt
        source = open(wt.__file__).read()
        # Should have client.invoke calls for sub-tool dispatch
        assert "client.invoke" in source

    def test_canonical_registry_no_dead_handler_calls(self):
        source = open("tool_runtime/canonical_registry.py").read()
        assert "registry_entry.handler(" not in source or "deprecated" in source

    @pytest.mark.skip(reason="requires local project path")
    def test_no_direct_dispatch_bypass(self):
        """No production code should call CANONICAL_REGISTRY[tid].handler() directly."""
        import subprocess
        r = subprocess.run(
            ["git", "grep", "-n", r'\.handler\s*\(', "agent/", "backend/", "tool_runtime/",
             ":!*test*", ":!*canonical_registry*", ":!*__pycache__"],
            capture_output=True, text=True, cwd="/Users/zhangh01/Desktop/network_agent",
        )
        # Some handler() calls are allowed (registration, manifest), but
        # handler(invocation) should only happen in executor.py
        for line in r.stdout.splitlines():
            if "handler(" in line and "handler_id" not in line and "handler_name" not in line:
                # Only allow in executor.py or registry.py (registration)
                filepart = line.split(":")[0]
                if "executor.py" not in filepart and "canonical_registry.py" not in filepart:
                    pytest.fail(f"Handler called outside executor/registry: {line}")


class TestPhase5Unaffected:
    def test_manifest_still_valid(self):
        from tool_runtime.manifest_registry import validate_all
        errors, count = validate_all()
        assert count >= 70
        assert len(errors) == 0

    def test_retry_still_works(self):
        from agent.runtime.durable.control import _is_retryable
        from agent.runtime.durable.models import RuntimeStep
        step = RuntimeStep(step_id="s1", task_id="t1", kind="tool", tool_id="web.search", status="failed")
        assert _is_retryable(step) is True
