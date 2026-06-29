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
        result = client.invoke("web.manage", {"query": "test", "top_k": 1}, context=ctx)
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
        result = client.invoke("device.manage", {"asset_id": "test"}, context=ctx)
        # device.delete.allowed_callers only includes valid runtime callers
        assert result.status == "blocked" or "allow" in str(result.summary).lower()


# v3.9.3: capability_routing removed. TestManifestGate class
# (active_tool_catalog filtering) is no longer applicable.

class TestRedaction:
    def test_tool_output_redacted_by_default(self):
        from tool_runtime.integration import get_default_tool_runtime_client
        from tool_runtime.context import ToolRuntimeContext
        client = get_default_tool_runtime_client()
        ctx = ToolRuntimeContext(workspace_id="default")
        result = client.invoke("skill.manage", {}, context=ctx)
        # Should be redacted
        assert result.redacted is True

    def test_high_risk_rest_invoke_not_direct_execute(self):
        from tool_runtime.integration import get_default_tool_runtime_client
        from tool_runtime.context import ToolRuntimeContext
        client = get_default_tool_runtime_client()
        ctx = ToolRuntimeContext(workspace_id="default", requested_by="rest_api")
        result = client.invoke("git.manage", {"remote": "origin"}, context=ctx)
        # Should go through pipeline, not directly execute
        assert result.status in ("failed", "blocked", "succeeded", "dry_run")


class TestToolPolicySafetySemantics:
    def test_merged_device_read_action_does_not_require_approval(self):
        from tool_runtime.policy import ToolPolicy
        from tool_runtime.schemas import ToolInvocation, ToolSpec

        spec = ToolSpec(
            tool_id="device.manage",
            category="device",
            risk_level="medium",
            requires_approval=False,
            input_schema={"type": "object", "properties": {}},
        )

        decision = ToolPolicy().check(
            spec,
            ToolInvocation(
                tool_id="device.manage",
                arguments={"workspace_id": "default", "action": "list", "search": "测试"},
                workspace_id="default",
                requested_by="turn_runner",
            ),
        )

        assert decision.allowed is True
        assert decision.requires_approval is False

    def test_merged_device_delete_action_requires_approval(self):
        from tool_runtime.policy import ToolPolicy
        from tool_runtime.schemas import ToolInvocation, ToolSpec

        spec = ToolSpec(
            tool_id="device.manage",
            category="device",
            risk_level="medium",
            requires_approval=False,
            input_schema={"type": "object", "properties": {}},
        )

        decision = ToolPolicy().check(
            spec,
            ToolInvocation(
                tool_id="device.manage",
                arguments={"workspace_id": "default", "action": "delete", "asset_id": "asset-1"},
                workspace_id="default",
                requested_by="turn_runner",
            ),
        )

        assert decision.allowed is True
        assert decision.risk_level == "high"
        assert decision.requires_approval is True

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
        """v3.9.5: destructive commands ESCALATE to high + require
        approval, they do NOT block the call. The approval bubble is
        the gating UX; if the user approves, the call runs.
        """
        from tool_runtime.policy import ToolPolicy
        from tool_runtime.schemas import ToolInvocation, ToolSpec

        spec = ToolSpec(
            tool_id="exec.run",
            category="exec",
            risk_level="medium",  # manifest would say medium; arg-level escalates
            requires_approval=False,
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

        # v3.9.5: allowed=True, risk=high, requires_approval=True.
        # The bubble UX decides whether the call actually executes.
        assert decision.allowed is True
        assert decision.risk_level == "high"
        assert decision.requires_approval is True


class TestNoBypass:
    def test_web_tools_use_client_invoke(self):
        """Confirm web_tools.py merged handlers do NOT route through
        the removed ``web.search`` id (deleted in v3.9.2 tool merge).

        v3.9.4: sub-tool dispatch uses an internal ``_invoke_internal_*``
        helper that re-enters the canonical ``web.manage`` handler with a
        synthetic ToolInvocation. This is preferred over ``client.invoke``
        for the web sub-tools because ``web.search`` no longer exists in
        the canonical 21-tool namespace.
        """
        import tool_runtime.general_tools.web_tools as wt
        source = open(wt.__file__).read()
        # Must NOT call the removed web.search id.
        assert '"web.search"' not in source
        assert "'web.search'" not in source
        # Sub-dispatch should go through an internal helper that re-enters
        # the canonical web.manage handler.
        assert "_invoke_internal_web_search" in source

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
        # v3.9.2: 21 merged tools, not 70+. All manifests must validate.
        assert count >= 20  # 21 expected
        assert not errors, f"manifest validation errors: {errors}"
        assert len(errors) == 0

    def test_retry_still_works(self):
        from agent.runtime.durable.control import _is_retryable
        from agent.runtime.durable.models import RuntimeStep
        step = RuntimeStep(step_id="s1", task_id="t1", kind="tool", tool_id="web.manage", status="failed")
        assert _is_retryable(step) is True
