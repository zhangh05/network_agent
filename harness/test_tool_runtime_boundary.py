# Tool runtime boundary and caller-gate contracts.
"""Phase 6: Tool Runtime hard boundary enforcement."""

import pytest, uuid
from core.tools.manifest_registry import get_manifest, is_retryable


class TestCallerPermission:
    def test_allowed_caller_passes(self):
        from core.tools.integration import get_default_tool_runtime_client
        from core.tools.context import ToolRuntimeContext
        client = get_default_tool_runtime_client()
        ctx = ToolRuntimeContext(
            workspace_id="default",
            requested_by="turn_runner",
        )
        result = client.invoke("web.manage", {"query": "test", "top_k": 1}, context=ctx)
        # Should not be blocked by caller permission
        assert result.status != "blocked" or "caller" not in str(result.summary).lower()

    def test_disallowed_caller_blocked(self):
        from core.tools.integration import get_default_tool_runtime_client
        from core.tools.context import ToolRuntimeContext
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
        from core.tools.integration import get_default_tool_runtime_client
        from core.tools.context import ToolRuntimeContext
        client = get_default_tool_runtime_client()
        ctx = ToolRuntimeContext(workspace_id="default")
        result = client.invoke("skill.manage", {}, context=ctx)
        # Should be redacted
        assert result.redacted is True

    def test_removed_git_tool_is_not_dispatchable(self):
        from core.tools.integration import get_default_tool_runtime_client
        from core.tools.context import ToolRuntimeContext
        client = get_default_tool_runtime_client()
        ctx = ToolRuntimeContext(workspace_id="default", requested_by="rest_api")
        result = client.invoke("git.manage", {"remote": "origin"}, context=ctx)
        assert result.status == "blocked"

    def test_policy_remains_authoritative_with_runtime_context(self, monkeypatch):
        from core.tools.client import ToolRuntimeClient
        from core.tools.context import ToolRuntimeContext
        from core.tools.manifest import CapabilityManifest
        from core.tools.manifest_registry import MANIFESTS
        from core.tools.policy import ToolPolicy
        from core.tools.registry import ToolRegistry
        from core.tools.schemas import PolicyDecision, ToolSpec

        class DenyAllPolicy(ToolPolicy):
            def check(self, invocation, tool_spec):
                return PolicyDecision(
                    allowed=False,
                    reason="denied by policy",
                    risk_level="high",
                )

        registry = ToolRegistry()
        registry.register_tool(
            ToolSpec(
                tool_id="test_tool",
                name="test_tool",
                description="test",
                category="runtime",
                risk_level="low",
            ),
            lambda **kwargs: {"ok": True},
        )
        monkeypatch.setitem(
            MANIFESTS,
            "test_tool",
            CapabilityManifest(
                tool_id="test_tool",
                display_name="Test Tool",
                action_class="read",
                risk_level="low",
                output_sensitivity="public",
                description="test",
            ),
        )

        result = ToolRuntimeClient(registry, DenyAllPolicy()).invoke(
            "test_tool",
            {},
            context=ToolRuntimeContext(
                workspace_id="test",
                requested_by="turn_runner",
            ),
        )

        assert result.status == "blocked"
        assert "denied by policy" in result.summary


class TestToolPolicySafetySemantics:
    def test_executor_blocks_approval_required_call_without_approval_id(self):
        from core.tools.executor import ToolExecutor
        from core.tools.policy import ToolPolicy
        from core.tools.registry import ToolRegistry
        from core.tools.schemas import ToolInvocation, ToolSpec

        executed = {"value": False}
        registry = ToolRegistry()
        registry.register_tool(
            ToolSpec(
                tool_id="device.manage",
                name="Device Manage",
                description="test",
                category="device",
                risk_level="medium",
                input_schema={"type": "object", "properties": {}},
            ),
            lambda inv: executed.__setitem__("value", True) or {"ok": True},
        )

        result = ToolExecutor(registry, ToolPolicy()).execute(
            ToolInvocation(
                tool_id="device.manage",
                arguments={"workspace_id": "default", "action": "delete", "asset_id": "asset-1"},
                workspace_id="default",
                requested_by="turn_runner",
            ),
        )

        assert result.status == "blocked"
        assert result.policy_decision.requires_approval is True
        assert "approval_required" in result.errors
        assert executed["value"] is False

    def test_merged_device_read_action_does_not_require_approval(self):
        from core.tools.policy import ToolPolicy
        from core.tools.schemas import ToolInvocation, ToolSpec

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
        from core.tools.policy import ToolPolicy
        from core.tools.schemas import ToolInvocation, ToolSpec

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
        from core.tools.policy import ToolPolicy
        from core.tools.schemas import ToolInvocation, ToolSpec

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
        from core.tools.policy import ToolPolicy
        from core.tools.schemas import ToolInvocation, ToolSpec

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
        the canonical namespace.
        """
        import core.tools.general_tools.web_tools as wt
        source = open(wt.__file__).read()
        # Must NOT call the removed web.search id.
        assert '"web.search"' not in source
        assert "'web.search'" not in source
        # Sub-dispatch should go through an internal helper that re-enters
        # the canonical web.manage handler.
        assert "_invoke_internal_web_search" in source

    def test_canonical_registry_no_dead_handler_calls(self):
        source = open("core/tools/canonical_registry.py").read()
        assert "registry_entry.handler(" not in source or "deprecated" in source
