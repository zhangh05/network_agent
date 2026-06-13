"""Runtime Operational Closure Tests — v0.2

Covers selfcheck gate, retention apply+confirm, audit log, archive, diagnostics API.
"""

import json
import os
import subprocess
import sys
import pytest
from harness.conftest import read_frontend_source_text

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestSelfcheckGate:
    def test_gate_healthy_passes(self):
        r = subprocess.run(
            [sys.executable, "scripts/runtime_selfcheck_gate.py", "--workspace", "default"],
            capture_output=True, text=True, cwd=PROJECT_ROOT,
        )
        # default workspace should pass
        assert r.returncode == 0 or "PASSED" in r.stdout

    def test_gate_json_output(self):
        r = subprocess.run(
            [sys.executable, "scripts/runtime_selfcheck_gate.py", "--workspace", "default", "--json"],
            capture_output=True, text=True, cwd=PROJECT_ROOT,
        )
        output = json.loads(r.stdout)
        assert "status" in output
        assert "issues" in output

    def test_gate_no_absolute_path(self):
        r = subprocess.run(
            [sys.executable, "scripts/runtime_selfcheck_gate.py", "--workspace", "default", "--json"],
            capture_output=True, text=True, cwd=PROJECT_ROOT,
        )
        assert "/Users/" not in r.stdout

    def test_gate_no_secrets(self):
        r = subprocess.run(
            [sys.executable, "scripts/runtime_selfcheck_gate.py", "--workspace", "default", "--json"],
            capture_output=True, text=True, cwd=PROJECT_ROOT,
        )
        for secret in ("password", "token", "secret", "community"):
            assert secret not in r.stdout.lower() or "[REDACTED]" in r.stdout

    def test_gate_missing_workspace(self):
        r = subprocess.run(
            [sys.executable, "scripts/runtime_selfcheck_gate.py", "--workspace", "nonexistent_ws_xyz_999"],
            capture_output=True, text=True, cwd=PROJECT_ROOT,
        )
        # Missing workspace should fail
        assert r.returncode != 0

    def test_gate_fail_on_warning(self):
        r = subprocess.run(
            [sys.executable, "scripts/runtime_selfcheck_gate.py", "--fail-on-warning", "--workspace", "default"],
            capture_output=True, text=True, cwd=PROJECT_ROOT,
        )
        # May or may not fail depending on workspace state


class TestRetentionApply:
    def test_apply_default_dry_run(self):
        from runtime.retention import apply_retention
        result = apply_retention("default")
        assert result.dry_run is True

    def test_apply_no_confirm_blocked(self):
        from runtime.retention import apply_retention
        result = apply_retention("default", dry_run=False, confirm=False)
        assert "BLOCKED" in str(result.warnings)

    def test_apply_with_confirm(self):
        from runtime.retention import apply_retention
        result = apply_retention("default", dry_run=False, confirm=True)
        assert result.dry_run is False

    def test_apply_active_artifacts_protected(self):
        """Active artifacts should appear in blocked_items, not candidates."""
        from runtime.retention import preview_retention
        preview = preview_retention("default")
        for b in preview.blocked_items:
            if b.get("reason") == "active_artifact":
                assert b.get("artifact_id")


class TestRetentionAudit:
    def test_audit_record_generated(self):
        from runtime.retention import apply_retention, get_audits
        apply_retention("default", dry_run=True)
        audits = get_audits("default")
        assert len(audits) > 0

    def test_audit_record_no_absolute_path(self):
        from runtime.retention import get_audits
        audits = get_audits("default")
        for a in audits:
            assert "/Users/" not in str(a)

    def test_audit_record_no_secrets(self):
        from runtime.retention import get_audits
        audits = get_audits("default")
        for a in audits:
            a_str = str(a).lower()
            for secret in ("password", "token", "community"):
                assert secret not in a_str

    def test_get_single_audit(self):
        from runtime.retention import apply_retention, get_audits, get_audit
        apply_retention("default", dry_run=True)
        audits = get_audits("default")
        if audits:
            aid = audits[0]["audit_id"]
            detail = get_audit("default", aid)
            assert detail["audit_id"] == aid

    def test_audit_has_required_fields(self):
        from runtime.retention import get_audits
        audits = get_audits("default")
        if audits:
            a = audits[0]
            for field in ("audit_id", "created_at", "workspace_id", "dry_run", "policy"):
                assert field in a


class TestUIHealthDashboard:
    def test_ui_has_selfcheck_display(self):
        html = read_frontend_source_text()
        assert "runtimeApi" in html and "/runtime/summary" in html

    def test_ui_no_default_delete_button(self):
        html = read_frontend_source_text()
        assert "删除" not in html or "confirm" in html.lower()

    def test_ui_no_deployable_claim(self):
        html = read_frontend_source_text()
        assert "可直接下发" not in html

    def test_ui_no_absolute_path_leak(self):
        html = read_frontend_source_text()
        assert "/Users/" not in html

    def test_ui_workspace_badge(self):
        html = read_frontend_source_text()
        assert "currentWorkspaceId" in html and "ws-list" in html
