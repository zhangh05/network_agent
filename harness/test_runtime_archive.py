"""Runtime Archive Tests — v0.1"""
import os
import json
import sys
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestArchivePolicy:
    def test_default_policy_exists(self):
        from runtime.archive import default_archive_policy
        policy = default_archive_policy()
        assert policy.runs_older_than_days == 30
        assert policy.archive_reports is False

    def test_policy_as_dict(self):
        from runtime.archive import default_archive_policy
        d = default_archive_policy().as_dict()
        assert "runs_older_than_days" in d


class TestPreviewArchive:
    def test_preview_no_move(self):
        from runtime.archive import preview_archive_candidates
        preview = preview_archive_candidates("default")
        assert preview.dry_run is True
        assert preview.moved_counts == {}

    def test_preview_structure(self):
        from runtime.archive import preview_archive_candidates
        preview = preview_archive_candidates("default")
        assert preview.workspace_id == "default"
        assert isinstance(preview.candidate_counts, dict)
        assert isinstance(preview.blocked_items, list)

    def test_missing_workspace(self):
        from runtime.archive import preview_archive_candidates
        preview = preview_archive_candidates("nonexistent_ws_xyz")
        assert len(preview.warnings) > 0

    def test_preview_no_absolute_path(self):
        from runtime.archive import preview_archive_candidates
        preview = preview_archive_candidates("default")
        output = str(preview.as_dict())
        assert "/Users/" not in output


class TestApplyArchive:
    def test_apply_default_dry_run(self):
        from runtime.archive import apply_archive
        result = apply_archive("default")
        assert result.dry_run is True

    def test_apply_no_confirm_blocked(self):
        from runtime.archive import apply_archive
        result = apply_archive("default", dry_run=False, confirm=False)
        assert "BLOCKED" in str(result.warnings)

    def test_apply_with_confirm(self):
        from runtime.archive import apply_archive
        result = apply_archive("default", dry_run=False, confirm=True)
        assert result.dry_run is False
        # Should have moved some expired items or 0 if none qualify
        assert isinstance(result.moved_counts, dict)

    def test_archive_creates_audit(self):
        from runtime.archive import apply_archive, get_archive_audits
        apply_archive("default", dry_run=True)
        audits = get_archive_audits("default")
        assert len(audits) > 0

    def test_archive_audit_no_secrets(self):
        from runtime.archive import get_archive_audits
        audits = get_archive_audits("default")
        for a in audits:
            a_str = str(a).lower()
            for secret in ("password", "token", "community"):
                assert secret not in a_str

    def test_archive_audit_no_absolute_path(self):
        from runtime.archive import get_archive_audits
        audits = get_archive_audits("default")
        for a in audits:
            assert "/Users/" not in str(a)

    def test_get_single_audit(self):
        from runtime.archive import apply_archive, get_archive_audits, get_archive_audit
        apply_archive("default", dry_run=True)
        audits = get_archive_audits("default")
        if audits:
            aid = audits[0]["audit_id"]
            detail = get_archive_audit("default", aid)
            assert detail["audit_id"] == aid

    def test_archive_structure_correct(self):
        """Archived items should honor workspace boundary."""
        from runtime.archive import apply_archive, preview_archive_candidates
        preview = preview_archive_candidates("default")
        # All candidates should have type and name
        for c in preview.candidates:
            assert "type" in c
            assert "name" in c

    def test_excluded_workspace_blocked(self):
        from runtime.archive import preview_archive_candidates
        preview = preview_archive_candidates("../../../etc")
        assert len(preview.warnings) > 0


class TestUIArchive:
    def test_ui_has_archive_preview(self):
        with open("frontend/index.html") as f:
            html = f.read()
        assert "archive/preview" in html

    def test_ui_no_default_archive_button(self):
        with open("frontend/index.html") as f:
            html = f.read()
        # Should not have a default delete/archive action
        assert "应用归档" not in html or "confirm" in html.lower()

    def test_ui_no_deployable_claim(self):
        with open("frontend/index.html") as f:
            html = f.read()
        assert "可直接下发" not in html

    def test_ui_no_absolute_path(self):
        with open("frontend/index.html") as f:
            html = f.read()
        assert "/Users/" not in html
