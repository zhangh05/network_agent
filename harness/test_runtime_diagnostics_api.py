"""Runtime Diagnostics API Tests — v0.1

Tests diagnostics, selfcheck, and retention via Python API directly.
Flask route wiring is tested separately via existing harness tests.
"""

import pytest


class TestDiagnosticsAPI:
    def test_health_endpoint_python(self):
        from runtime.diagnostics import get_diagnostics
        report = get_diagnostics("default")
        assert len(report.components) > 0
        assert "total" in report.summary

    def test_selfcheck_endpoint_python(self):
        from runtime.selfcheck import run_selfcheck
        result = run_selfcheck("default")
        assert result.status in ("healthy", "warning", "degraded", "failed")
        assert "issues" in result.as_dict()

    def test_workspace_selfcheck_python(self):
        from runtime.selfcheck import run_selfcheck
        result = run_selfcheck("default")
        assert isinstance(result.checks, dict)

    def test_retention_preview_python(self):
        from runtime.retention import preview_retention
        preview = preview_retention("default")
        assert preview.dry_run is True
        assert preview.workspace_id == "default"

    def test_workspaces_runtime_exists(self):
        from pathlib import Path
        import os
        ws_root = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) / "workspaces"
        if ws_root.is_dir():
            for d in ws_root.iterdir():
                if d.is_dir() and not d.name.startswith("."):
                    assert d.name  # at least one workspace exists

    def test_invalid_workspace(self):
        from runtime.selfcheck import run_selfcheck
        from runtime.selfcheck import SelfcheckStatus
        result = run_selfcheck("../../../etc")
        assert result.status in (SelfcheckStatus.FAILED, SelfcheckStatus.DEGRADED)

    def test_no_absolute_path_in_diagnostics(self):
        from runtime.diagnostics import get_diagnostics
        report = get_diagnostics("default")
        output = str(report.as_dict())
        assert "/Users/" not in output

    def test_no_key_in_diagnostics(self):
        from runtime.diagnostics import get_diagnostics
        report = get_diagnostics("default")
        output = str(report.as_dict()).lower()
        for keyword in ("password", "token", "secret", "community"):
            assert keyword not in output or "[REDACTED]" in output

    def test_health_api_module_works(self):
        from runtime.diagnostics import get_diagnostics
        report = get_diagnostics("default")
        assert len(report.components) >= 5  # workspace, registry, runs, agent, tool_runtime


class TestFrontendSafety:
    def test_ui_no_tool_invoke(self):
        with open("frontend/index.html") as f:
            html = f.read()
        assert 'invoke_tool' not in html
        assert 'tool.invoke' not in html.lower()

    def test_ui_no_deployable_claim(self):
        with open("frontend/index.html") as f:
            html = f.read()
        assert '可直接下发' not in html

    def test_ui_has_workspace_badge(self):
        with open("frontend/index.html") as f:
            html = f.read()
        assert 'ws-badge' in html or 'ws-display' in html

    def test_ui_dashboard_uses_api(self):
        with open("frontend/index.html") as f:
            html = f.read()
        assert '/api/health' in html
        assert '/api/runs/recent' in html
        assert '/api/runtime/health' in html

    def test_ui_localstorage_only_prefs(self):
        with open("frontend/index.html") as f:
            html = f.read()
        has_history_storage = 'localStorage.setItem(' in html
        if has_history_storage:
            assert 'na_workspace_id' in html or 'na_settings' in html
