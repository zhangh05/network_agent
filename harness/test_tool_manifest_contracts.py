# Canonical capability manifest contracts.
"""Phase 5: Capability Manifest — all tools declared, policy derived."""

import pytest
from core.tools.manifest_registry import (
    MANIFESTS, get_manifest, validate_all, is_retryable,
)
from core.tools.manifest import CapabilityManifest


class TestManifestCompleteness:
    def test_all_tools_have_manifest(self):
        from core.tools.canonical_registry import CANONICAL_REGISTRY
        for tid in CANONICAL_REGISTRY:
            assert tid in MANIFESTS, f"Missing manifest for {tid}"
        assert len(MANIFESTS) >= len(CANONICAL_REGISTRY)

    def test_all_manifests_validate(self):
        errors, count = validate_all()
        assert count > 0, "No manifests found"
        assert len(errors) == 0, f"Validation errors: {errors}"

    def test_no_duplicate_manifest(self):
        ids = list(MANIFESTS.keys())
        assert len(ids) == len(set(ids)), f"Duplicate manifest IDs: {[x for x in ids if ids.count(x) > 1]}"

    def test_read_only_skill_tools_have_manifest(self):
        # v3.9.2: all 4 skill tools merged into skill.manage.
        m = MANIFESTS["skill.manage"]
        assert m is not None, "Missing manifest for skill.manage"
        assert m.action_class == "read"
        assert m.risk_level == "low"
        assert not m.requires_approval

    def test_tool_specs_derive_risk_from_manifest(self):
        from core.tools.canonical_registry import to_tool_specs

        specs = {spec.tool_id: spec for spec, _ in to_tool_specs()}
        for tid, manifest in MANIFESTS.items():
            assert tid in specs
            assert specs[tid].risk_level == manifest.risk_level
            assert specs[tid].requires_approval == manifest.requires_approval


class TestRiskAndApproval:
    def test_high_risk_requires_approval(self):
        for tid, m in MANIFESTS.items():
            if m.risk_level in ("high", "critical"):
                assert m.requires_approval, f"{tid}: high/critical must require approval"

    def test_destructive_requires_approval(self):
        for tid, m in MANIFESTS.items():
            if m.destructive:
                assert m.requires_approval, f"{tid}: destructive must require approval"

    def test_device_manage_base_policy_is_medium(self):
        # v3.9.7: merged tools carry base risk only. action=delete
        # escalates at runtime; action=list/get never opens approval.
        m = MANIFESTS["device.manage"]
        assert m.risk_level == "medium"
        assert not m.destructive
        assert not m.requires_approval


class TestSecretFields:
    def test_exec_run_has_secret_fields(self):
        m = MANIFESTS["exec.run"]
        assert {"password", "code", "env_vars"}.issubset(m.secret_fields)

    def test_memory_has_sensitive_output(self):
        # v3.9.2: memory.manage is the merged tool; output_sensitivity=sensitive.
        m = MANIFESTS["memory.manage"]
        assert m.output_sensitivity == "sensitive"


class TestIdempotencyAndRetry:
    def test_safe_to_retry_tools_are_retryable(self):
        # v3.9.2: merged tools whose manifest marks safe_to_retry.
        # v3.16.2: agent.manage is now safe_to_retry (spawn moved to named tools).
        for tid in ("web.manage", "browser.manage", "agent.manage"):
            assert is_retryable(tid), f"{tid} should be retryable"

    def test_destructive_not_retryable(self):
        # v3.9.2: destructive merged tools.
        assert not is_retryable("device.manage")
        assert not is_retryable("system.manage")

    def test_non_idempotent_not_retryable(self):
        # exec.run is unsafe; Python and shell execution remain available but
        # are never mechanically replayed.
        assert not is_retryable("exec.run")
        assert is_retryable("agent.manage")


class TestAllowedCallers:
    def test_default_callers_include_all_runtimes(self):
        m = MANIFESTS["web.manage"]
        assert "turn_runner" in m.allowed_callers

    def test_subagent_restricted_where_needed(self):
        m = MANIFESTS["agent.manage"]
        assert "turn_runner" in m.allowed_callers


class TestApprovalReason:
    def test_approval_has_reason_template(self):
        approval_tools = [tid for tid, m in MANIFESTS.items() if m.requires_approval]
        for tid in approval_tools:
            m = MANIFESTS[tid]
            assert m.approval_reason_template, f"{tid}: must have approval_reason_template"
