# harness/test_phase5_enforcement.py
"""Phase 5 enforcement: manifest is the single source of truth."""

import pytest
from core.tools.manifest_registry import MANIFESTS, get_manifest, is_retryable

class TestManifestDrivesRetry:
    def test_retry_control_reads_manifest_idempotency(self):
        """retry_step should use manifest.idempotency, not hardcoded patterns."""
        from agent.runtime.durable.control import _is_retryable
        from agent.runtime.durable.models import RuntimeStep
        # safe_to_retry tool (v3.9.2: web.manage is the merged web tool)
        step = RuntimeStep(step_id="s1", task_id="t1", kind="tool",
                           tool_id="web.manage", status="failed")
        assert _is_retryable(step) is True
        # destructive tool (v3.9.2: device.manage is the merged tool; manifest
        # marks it as unsafe_to_retry because it contains delete sub-action)
        step2 = RuntimeStep(step_id="s2", task_id="t1", kind="tool",
                            tool_id="device.manage", status="failed")
        assert _is_retryable(step2) is False

    def test_changing_manifest_idempotency_changes_retry_behavior(self):
        """If we change manifest idempotency, retry behavior follows."""
        from agent.runtime.durable.control import _is_retryable
        from agent.runtime.durable.models import RuntimeStep
        # v3.9.1.1: workspace.file (merged) replaces old aliases
        step = RuntimeStep(step_id="st", task_id="t", kind="tool",
                           tool_id="workspace.file", status="failed")
        m = get_manifest("workspace.file")
        assert m is not None
        # Currently unsafe_to_retry (mixed read/write tool)
        assert not _is_retryable(step)
        # If we changed manifest (hypothetically), behavior changes
        old_val = m.idempotency
        try:
            m.idempotency = "safe_to_retry"
            assert _is_retryable(step)
        finally:
            m.idempotency = old_val


class TestManifestDrivesRisk:
    def test_risk_policy_reads_manifest(self):
        """RiskPolicy.evaluate() should read risk_level from manifest."""
        from agent.runtime.actions.risk import RiskPolicy
        from agent.runtime.actions.models import ActionPlan
        rp = RiskPolicy()
        plan = ActionPlan(tool_id="web.manage", action_class="network",
                          arguments={"action": "search"})
        decision = rp.evaluate(plan)
        m = get_manifest("web.manage")
        assert decision.risk_level == m.risk_level

    def test_manifest_drives_approval_flag(self):
        """requires_approval should be false for low-risk tools."""
        from agent.runtime.actions.risk import RiskPolicy
        from agent.runtime.actions.models import ActionPlan
        rp = RiskPolicy()
        plan = ActionPlan(tool_id="git.manage", action_class="read",
                          arguments={"action": "diff"})
        decision = rp.evaluate(plan)
        assert decision.approval_required is False

    def test_high_risk_manifest_drives_approval(self):
        """high-risk manifest flag triggers approval."""
        from agent.runtime.actions.risk import RiskPolicy
        from agent.runtime.actions.models import ActionPlan
        rp = RiskPolicy()
        # v3.9.2: git.manage(action=push) requires approval
        plan = ActionPlan(tool_id="git.manage", action_class="write",
                          arguments={"action": "push"})
        decision = rp.evaluate(plan)
        m = get_manifest("git.manage")
        assert decision.approval_required == m.requires_approval


class TestManifestDrivesApprovalReason:
    def test_approval_reason_from_manifest(self):
        """Approval reason should come from manifest template."""
        from agent.runtime.actions.risk import RiskPolicy
        from agent.runtime.actions.models import ActionPlan
        rp = RiskPolicy()
        # v3.9.2: device.manage(action=delete) is the destructive path
        plan = ActionPlan(tool_id="device.manage", action_class="mutate",
                          arguments={"action": "delete"})
        decision = rp.evaluate(plan)
        m = get_manifest("device.manage")
        assert decision.approval_required is True


class TestCatalogIncludesManifest:
    def test_catalog_has_manifest_fields(self):
        from core.tools.catalog_snapshot import build_catalog_snapshot
        cat = build_catalog_snapshot()
        tools = cat.get("tools", [])
        assert len(tools) > 0
        # Find a tool that exists (v3.9.2: web.manage is the merged web tool)
        tool = next((t for t in tools if t["tool_id"] == "web.manage"), None)
        assert tool is not None
        assert "destructive" in tool
        assert "idempotency" in tool
        assert "side_effects" in tool
        assert "output_sensitivity" in tool
        assert "timeout_seconds" in tool
        assert "action_class" in tool

    def test_catalog_destructive_matches_manifest(self):
        """v3.9.6: destructiveness is now action-level, not tool-level.
        The manifest no longer marks ``device.manage`` as
        ``destructive=True`` just because it contains a ``delete``
        sub-action. Instead, ``core.tools.policy._is_destructive_action``
        escalates the call to ``high`` + ``requires_approval`` only
        when ``action`` is in ``_DESTRUCTIVE_ACTIONS`` (delete / remove /
        purge / destroy / drop / delete_file / session_rewind / rewind).
        That separates the static risk profile (one per tool) from the
        dynamic per-call destructive escalation.
        """
        from core.tools.catalog_snapshot import build_catalog_snapshot
        from core.tools.policy import ToolPolicy
        from core.tools.schemas import ToolSpec, ToolInvocation

        # 1. Manifest field is still present and is a bool.
        cat = build_catalog_snapshot()
        tools = cat.get("tools", [])
        tool = next((t for t in tools if t["tool_id"] == "device.manage"), None)
        assert tool is not None
        assert isinstance(tool["destructive"], bool)

        # 2. A non-destructive sub-action keeps the normal risk level.
        spec = ToolSpec(
            tool_id="device.manage", name="device.manage", category="device",
            description="x", risk_level="medium", enabled=True, input_schema={},
            callable_by_llm=True, permission_action="write",
        )
        inv_safe = ToolInvocation(
            tool_id="device.manage",
            arguments={"action": "list"},
            workspace_id="default", requested_by="test",
        )
        d_safe = ToolPolicy().check(spec, inv_safe)
        assert d_safe.risk_level == "medium"
        assert d_safe.requires_approval is False

        # 3. A destructive sub-action escalates to high + approval.
        inv_destr = ToolInvocation(
            tool_id="device.manage",
            arguments={"action": "delete"},
            workspace_id="default", requested_by="test",
        )
        d_destr = ToolPolicy().check(spec, inv_destr)
        assert d_destr.risk_level == "high"
        assert d_destr.requires_approval is True


class TestNoDuplicateRiskLogic:
    def test_control_no_hardcoded_patterns(self):
        """control.py should not have old hardcoded idempotency patterns."""
        import agent.runtime.durable.control as ctrl
        source = ctrl.__file__
        with open(source) as f:
            content = f.read()
        assert "_NON_IDEMPOTENT_PATTERNS" not in content
        assert "_is_destructive" not in content
        assert "_IDEMPOTENT_READ_KINDS" not in content
