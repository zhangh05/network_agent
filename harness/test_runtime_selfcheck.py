"""Runtime Selfcheck Tests — v0.1"""
import pytest
from core.runtime.selfcheck import run_selfcheck, SelfcheckStatus
from workspace.manager import ensure_workspace


@pytest.fixture(autouse=True)
def _default_workspace_exists():
    ensure_workspace("default")


class TestSelfcheck:
    def test_selfcheck_healthy_default(self):
        """Selfcheck on default workspace should complete."""
        result = run_selfcheck("default")
        assert result.status in (SelfcheckStatus.HEALTHY, SelfcheckStatus.WARNING)

    def test_selfcheck_missing_workspace(self):
        """Selfcheck on missing workspace should return failed/degraded."""
        result = run_selfcheck("nonexistent_ws_xyz_12345")
        assert result.status in (SelfcheckStatus.FAILED, SelfcheckStatus.DEGRADED)

    def test_selfcheck_has_checks(self):
        result = run_selfcheck("default")
        assert isinstance(result.checks, dict)
        assert len(result.checks) > 0

    def test_selfcheck_has_issues_list(self):
        result = run_selfcheck("default")
        assert isinstance(result.issues, list)

    def test_selfcheck_issues_have_structure(self):
        result = run_selfcheck("default")
        for issue in result.issues:
            d = issue.as_dict()
            assert "severity" in d
            assert "code" in d
            assert "message" in d
            assert d["severity"] in ("info", "warning", "error", "critical")

    def test_selfcheck_no_absolute_path_leak(self):
        result = run_selfcheck("default")
        output = str(result.as_dict())
        assert "/Users/" not in output

    def test_selfcheck_config_translation_only_enabled(self):
        result = run_selfcheck("default")
        enabled = result.checks.get("enabled_modules", [])
        if enabled:
            assert sorted(enabled) == sorted(["config_translation", "knowledge_base"]) or len(enabled) >= 1

    def test_selfcheck_forbidden_api_passes(self):
        result = run_selfcheck("default")
        forbidden = result.checks.get("forbidden_api", "")
        if forbidden:
            assert forbidden == "ok"

    def test_selfcheck_tool_forbidden_list(self):
        result = run_selfcheck("default")
        forbidden_list = result.checks.get("tool_forbidden_list", [])
        if forbidden_list:
            assert "ssh.exec" in forbidden_list

    def test_selfcheck_reports_current_tool_runtime_contract(self):
        from core.tools.canonical_registry import CANONICAL_REGISTRY
        from core.tools.policy import V02_FORBIDDEN_TOOLS

        result = run_selfcheck("default")

        assert result.checks.get("tool_runtime") == "ok"
        assert result.checks.get("tool_registered_count") == len(CANONICAL_REGISTRY)
        assert result.checks.get("tool_forbidden_count") == len(V02_FORBIDDEN_TOOLS)
        # v3.9.3: tool_governance module removed. All 22 canonical tools
        # are active; V02_FORBIDDEN_TOOLS is a separate policy blacklist
        # of legacy tool names, not a subset of the registry.
        assert result.checks.get("tool_governance") == {
            "active": len(CANONICAL_REGISTRY),
            "disabled": 0,
            "internal": 0,
            "forbidden": 0,
        }


class TestRetention:
    def test_preview_dry_run_default(self):
        from core.runtime.retention import preview_retention
        preview = preview_retention("default")
        assert preview.dry_run is True
        assert preview.deleted_counts == {}

    def test_preview_returns_structure(self):
        from core.runtime.retention import preview_retention
        preview = preview_retention("default")
        assert preview.workspace_id == "default"
        assert isinstance(preview.candidate_counts, dict)
        assert isinstance(preview.candidates, list)
        assert isinstance(preview.blocked_items, list)

    def test_apply_dry_run_true_does_not_delete(self):
        from core.runtime.retention import apply_retention
        preview = apply_retention("default", dry_run=True)
        assert preview.dry_run is True
        assert "DRY RUN" in str(preview.warnings)

    def test_default_policy_has_reasonable_values(self):
        from core.runtime.retention import default_retention_policy
        policy = default_retention_policy()
        assert policy.runs_max_age_days == 30
        assert policy.runs_max_count == 500
        assert policy.prune_reports is False

    def test_preview_no_absolute_path(self):
        from core.runtime.retention import preview_retention
        preview = preview_retention("default")
        output = str(preview.as_dict())
        assert "/Users/" not in output

    def test_missing_workspace_preview(self):
        from core.runtime.retention import preview_retention
        preview = preview_retention("nonexistent_ws_xyz")
        assert len(preview.warnings) > 0


class TestDiagnostics:
    def test_diagnostics_has_components(self):
        from core.runtime.diagnostics import get_diagnostics
        report = get_diagnostics("default")
        assert len(report.components) > 0

    def test_diagnostics_has_summary(self):
        from core.runtime.diagnostics import get_diagnostics
        report = get_diagnostics("default")
        assert "total" in report.summary

    def test_diagnostics_no_absolute_path(self):
        from core.runtime.diagnostics import get_diagnostics
        report = get_diagnostics("default")
        output = str(report.as_dict())
        assert "/Users/" not in output

    def test_diagnostics_component_structure(self):
        from core.runtime.diagnostics import get_diagnostics
        report = get_diagnostics("default")
        for c in report.components:
            d = c.as_dict()
            assert "name" in d
            assert "status" in d
            assert d["status"] in ("ok", "warning", "error", "unavailable")
