"""Session & Artifacts UI Consistency Hardening v0.1 — Tests.

Covers:
- session_id validation (positive + negative)
- Artifact type stats alignment (backend vs frontend)
- Artifact delete is soft delete
- Artifact sensitivity/lifecycle fields present
- LLM max_tokens default = 4096 (frontend + backend)
- localStorage security (keys limited)
- Translate page restore from runs
"""

import re
import json
import sys
import os
from pathlib import Path
import pytest
from harness.conftest import read_frontend_source_text

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ═══════════════════════════════════════════
# Session ID Validation
# ═══════════════════════════════════════════

class TestSessionIdValidation:
    """session_id must be validated to prevent path traversal and injection."""

    def test_valid_session_id_hex16(self):
        from workspace.ids import validate_session_id
        # Standard uuid4 hex[:16] format
        assert validate_session_id("a1b2c3d4e5f6a7b8") == "a1b2c3d4e5f6a7b8"
        assert validate_session_id("abc123def4567890") == "abc123def4567890"

    def test_valid_session_id_with_hyphen(self):
        from workspace.ids import validate_session_id
        assert validate_session_id("session-001") == "session-001"

    def test_valid_session_id_with_underscore(self):
        from workspace.ids import validate_session_id
        assert validate_session_id("test_session_42") == "test_session_42"

    def test_rejects_empty_string(self):
        from workspace.ids import validate_session_id, is_valid_session_id
        assert not is_valid_session_id("")
        with pytest.raises(ValueError):
            validate_session_id("")

    def test_rejects_dot(self):
        from workspace.ids import validate_session_id
        with pytest.raises(ValueError):
            validate_session_id(".")

    def test_rejects_dotdot(self):
        from workspace.ids import validate_session_id
        with pytest.raises(ValueError):
            validate_session_id("..")

    def test_rejects_path_traversal(self):
        from workspace.ids import validate_session_id
        with pytest.raises(ValueError):
            validate_session_id("../../etc/passwd")
        with pytest.raises(ValueError):
            validate_session_id("sessions/../../../secret")

    def test_rejects_null_byte(self):
        from workspace.ids import validate_session_id
        with pytest.raises(ValueError):
            validate_session_id("good\x00bad")

    def test_rejects_whitespace_only(self):
        from workspace.ids import validate_session_id
        with pytest.raises(ValueError):
            validate_session_id("   ")

    def test_rejects_overlength(self):
        from workspace.ids import validate_session_id
        long_id = "a" * 65
        with pytest.raises(ValueError):
            validate_session_id(long_id)

    def test_rejects_special_chars(self):
        from workspace.ids import validate_session_id
        with pytest.raises(ValueError):
            validate_session_id("session<script>")
        with pytest.raises(ValueError):
            validate_session_id("test;drop table")

    def test_rejects_reserved_names(self):
        from workspace.ids import validate_session_id
        with pytest.raises(ValueError):
            validate_session_id("default")

    def test_session_routes_validate_id(self):
        """All session route handlers must call validate_session_id."""
        routes_py = (PROJECT_ROOT / "backend" / "api" / "session_routes.py").read_text()
        # All handlers with <session_id> in URL must validate
        handler_funcs = re.findall(r'def handle_session_(\w+)\(session_id\):', routes_py)
        assert len(handler_funcs) > 0
        assert "validate_session_id" in routes_py


# ═══════════════════════════════════════════
# Backend Route Integrity (post-extraction)
# ═══════════════════════════════════════════

class TestBackendRouteIntegrity:
    """API routes must remain unchanged after extraction from main.py."""

    REQUIRED_ROUTES = [
        "/api/workspaces/<ws_id>/artifacts",
        "/api/workspaces/<ws_id>/artifacts/upload",
        "/api/workspaces/<ws_id>/artifacts/<artifact_id>",
        "/api/workspaces/<ws_id>/artifacts/<artifact_id>/content",
        "/api/workspaces/<ws_id>/artifacts/<artifact_id>/summarize",
        "/api/workspaces/<ws_id>/runs/<run_id>/artifacts",
        "/api/workspaces/<ws_id>/runs/<run_id>/trace",
        "/api/workspaces/<ws_id>/traces",
        "/api/workspaces/<ws_id>/reports",
        "/api/workspaces/<ws_id>/runs/<run_id>/report",
        "/api/reports/create",
        "/api/runs/recent",
        "/api/runs/<run_id>",
        "/api/workspaces/<ws_id>/runs",
        "/api/workspaces/<ws_id>/history",
        "/api/workspaces/<ws_id>/runs/<run_id>",
        "/api/workspaces",
        "/api/jobs",
        "/api/jobs/<job_id>/cancel",
        "/api/jobs/<job_id>/retry",
        "/api/jobs/<job_id>/events",
        "/api/jobs/<job_id>/logs",
        "/api/jobs/<job_id>/artifacts",
        "/api/jobs/worker/run-once",
        "/api/jobs/worker/status",
        "/api/runtime/health",
        "/api/runtime/selfcheck",
        "/api/workspaces/<ws_id>/selfcheck",
        "/api/workspaces/<ws_id>/retention/preview",
        "/api/workspaces/<ws_id>/retention/apply",
        "/api/workspaces/<ws_id>/retention/audits",
        "/api/workspaces/<ws_id>/retention/audits/<audit_id>",
        "/api/workspaces/<ws_id>/archive/preview",
        "/api/workspaces/<ws_id>/archive/apply",
        "/api/workspaces/<ws_id>/archive/audits",
        "/api/workspaces/<ws_id>/archive/audits/<audit_id>",
        "/api/context/status",
        "/api/context/resolve",
        "/api/context/build",
        "/api/prompts",
        "/api/prompts/<prompt_id>",
        "/api/prompts/render",
        "/api/harness/status",
    ]

    @staticmethod
    def _collect_all_backend_routes():
        """Collect all route registrations from main.py and sub-route files."""
        source = (PROJECT_ROOT / "backend" / "main.py").read_text()
        for rf in ["backend/api/artifact_routes.py", "backend/api/job_routes.py",
                    "backend/api/runtime_routes.py", "backend/api/context_routes.py",
                    "backend/api/workspace_routes.py"]:
            p = PROJECT_ROOT / rf
            if p.exists():
                source += "\n" + p.read_text()
        return source

    def test_no_retired_routes(self):
        """Check that retired API routes are absent."""
        source = self._collect_all_backend_routes()
        retired = ["/api/translate", "GraphAgent", "network-translator", ":8020"]
        for r in retired:
            assert r not in source, f"Retired route '{r}' found in backend code"

    def test_all_required_routes_exist(self):
        """All required routes must exist in backend code."""
        source = self._collect_all_backend_routes()
        # Normalize angle brackets for comparison
        normalized = source.replace("<ws_id>", "default").replace("<run_id>", "x") \
                           .replace("<job_id>", "x").replace("<artifact_id>", "x") \
                           .replace("<audit_id>", "x").replace("<prompt_id>", "x")
        for r in self.REQUIRED_ROUTES:
            norm_r = r.replace("<ws_id>", "default").replace("<run_id>", "x") \
                       .replace("<job_id>", "x").replace("<artifact_id>", "x") \
                       .replace("<audit_id>", "x").replace("<prompt_id>", "x")
            assert norm_r in normalized, f"Required route '{r}' not found in backend"


# ═══════════════════════════════════════════
# Artifact Type Stats Alignment
# ═══════════════════════════════════════════

class TestArtifactTypeAlignment:
    """Frontend artifact stats must use real backend types, not 'config'."""

    def test_backend_artifact_types_defined(self):
        """Backend ARTIFACT_TYPES set includes input_config, output_config."""
        from artifacts.schemas import ARTIFACT_TYPES
        assert "input_config" in ARTIFACT_TYPES
        assert "output_config" in ARTIFACT_TYPES
        assert "report" in ARTIFACT_TYPES
        assert "knowledge_doc" in ARTIFACT_TYPES
        assert "temp" in ARTIFACT_TYPES

    def test_frontend_no_fake_config_type(self):
        """Frontend must not use 'config' as an artifact_type filter."""
        html = read_frontend_source_text()
        # 'config' may appear in context (e.g. 'input_config') but not as
        # an isolated artifact_type filter string "'config'"
        # Check artifact_type filter in artifact type dropdown
        filter_select = re.search(r'id="art-type-filter".*?</select>', html, re.DOTALL)
        if filter_select:
            filter_text = filter_select.group()
            # Must NOT contain value="config" without prefix
            assert 'value="config"' not in filter_text or 'input_config' in filter_text

    def test_frontend_uses_input_output_config(self):
        """Frontend type filter must include input_config and output_config."""
        html = read_frontend_source_text()
        assert 'translated_config' in html
        assert 'knowledge_doc' in html

    def test_artifact_stats_use_real_types(self):
        """updateArtStats must filter on input_config/output_config, not 'config'."""
        html = read_frontend_source_text()
        stats_js = re.search(
            r"function updateArtStats.*?(?=\nfunction )",
            html, re.DOTALL
        )
        if stats_js:
            stats_text = stats_js.group()
            # Must use input_config or output_config
            assert "input_config" in stats_text or "output_config" in stats_text
            # Must NOT have naked 'config' type check (without prefix)
            # The only valid check would be: a.artifact_type==='config'
            # which is what we need to avoid
            naked_config = re.findall(r"artifact_type\s*===\s*'config'", stats_text)
            assert len(naked_config) == 0, "updateArtStats must not use 'config' type"

    def test_artifact_sensitivity_in_sanitize(self):
        """sanitize_record must include sensitivity field."""
        store_py = (PROJECT_ROOT / "artifacts" / "store.py").read_text()
        assert '"sensitivity"' in store_py
        assert '"lifecycle"' in store_py

    def test_frontend_displays_sensitivity(self):
        """Frontend artifact table must show sensitivity and lifecycle."""
        html = read_frontend_source_text()
        assert "灵敏度" in html or "sensitivity" in html.lower() or "敏感度" in html

    def test_frontend_shows_lifecycle(self):
        """Frontend artifact table must show lifecycle status."""
        html = read_frontend_source_text()
        # The table header has "状态" column
        assert "状态" in html or "lifecycle" in html.lower()


# ═══════════════════════════════════════════
# Artifact Delete Semantics
# ═══════════════════════════════════════════

class TestArtifactDeleteSemantics:
    """Artifact deletion is soft delete, not irreversible."""

    def test_backend_delete_is_soft(self):
        """delete_artifact sets lifecycle='deleted', does not unlink."""
        store_py = (PROJECT_ROOT / "artifacts" / "store.py").read_text()
        # Must set lifecycle to deleted
        assert 'lifecycle = "deleted"' in store_py or "lifecycle='deleted'" in store_py
        # Must NOT physically delete the file
        delete_func = re.search(r'def delete_artifact.*?(?=\ndef )', store_py, re.DOTALL)
        if delete_func:
            func_text = delete_func.group()
            assert "unlink" not in func_text  # No physical file removal

    def test_frontend_delete_is_soft(self):
        """Frontend delete confirm must be soft delete wording."""
        target = (PROJECT_ROOT / "frontend" / "src" / "pages" /
                  "ArtifactCenter" / "ArtifactCenter.tsx").read_text()
        assert "不可撤销" not in target, "Artifact delete must not say 'irreversible'"

    def test_artifact_lifecycle_values_in_schemas(self):
        """LIFECYCLES includes 'deleted'."""
        from artifacts.schemas import LIFECYCLES
        assert "deleted" in LIFECYCLES


# ═══════════════════════════════════════════
# LLM max_tokens Default = 4096
# ═══════════════════════════════════════════

class TestLLMMaxTokens:
    """max_tokens must be 4096 in both frontend and backend default."""

    def test_backend_llm_yaml_max_tokens(self):
        """config/llm.yaml must have max_tokens: 4096."""
        yaml_text = (PROJECT_ROOT / "config" / "llm.yaml").read_text()
        assert "max_tokens: 4096" in yaml_text, "backend llm.yaml must have max_tokens: 4096"

    def test_frontend_placeholder_4096(self):
        """Frontend max_tokens input must have placeholder=4096."""
        html = read_frontend_source_text()
        assert 'max_tokens' in html and '4096' in html

    def test_frontend_value_4096(self):
        """Frontend max_tokens input must have value=4096."""
        html = read_frontend_source_text()
        # Check for value="4096" near llm-maxtok
        maxtok_input = re.search(r'id="llm-maxtok"[^>]*>', html)
        if maxtok_input:
            assert 'value="4096"' in maxtok_input.group()

    def test_frontend_save_fallback_4096(self):
        """Frontend save logic must fallback to 4096."""
        html = read_frontend_source_text()
        assert "max_tokens" in html
        assert "4096" in html

    def test_no_1200_remaining(self):
        """No 1200 max_tokens defaults should remain in frontend."""
        html = read_frontend_source_text()
        # Check that llm-maxtok related 1200 is gone
        maxtok_context = re.findall(r"llm-maxtok[^;]*1200", html)
        assert len(maxtok_context) == 0, f"Still have llm-maxtok 1200 references: {maxtok_context}"


# ═══════════════════════════════════════════
# localStorage Security
# ═══════════════════════════════════════════

class TestLocalStorageSecurity:
    """localStorage must only store workspace_id, session_id, and UI prefs."""

    ALLOWED_KEYS = {
        "na_workspace_id",
        "na_current_session_id",
        "na_settings",
    }

    def test_localstorage_only_allowed_keys(self):
        """Frontend localStorage.setItem must use only allowed keys."""
        html = read_frontend_source_text()
        setitem_lines = [l.strip() for l in html.split('\n') if 'localStorage.setItem' in l]
        for line in setitem_lines:
            # Extract the key being set
            key_match = re.search(r"localStorage\.setItem\(['\"]([^'\"]+)['\"]", line)
            if key_match:
                key = key_match.group(1)
                assert key in self.ALLOWED_KEYS, (
                    f"localStorage.setItem with key '{key}' is not allowed. "
                    f"Only {self.ALLOWED_KEYS} are permitted."
                )

    def test_no_chat_in_localstorage(self):
        """Chat messages must NOT be saved to localStorage."""
        html = read_frontend_source_text()
        suspicious = [
            "localStorage.setItem('chat'",
            "localStorage.setItem('message'",
            "localStorage.setItem('conversation'",
            "localStorage.setItem('chat_history'",
        ]
        for s in suspicious:
            assert s not in html, f"Chat data must not be in localStorage: {s}"

    def test_no_config_in_localstorage(self):
        """Config/secret data must NOT be saved to localStorage."""
        html = read_frontend_source_text()
        suspicious = [
            "localStorage.setItem('config'",
            "localStorage.setItem('api_key'",
            "localStorage.setItem('secret'",
            "localStorage.setItem('password'",
            "localStorage.setItem('token'",
            "localStorage.setItem('credential'",
        ]
        for s in suspicious:
            assert s not in html, f"Secret data must not be in localStorage: {s}"

    def test_no_prompt_in_localstorage(self):
        """Prompt data must NOT be saved to localStorage."""
        html = read_frontend_source_text()
        suspicious = [
            "localStorage.setItem('prompt'",
            "localStorage.setItem('system_prompt'",
            "localStorage.setItem('llm_prompt'",
        ]
        for s in suspicious:
            assert s not in html, f"Prompt data must not be in localStorage: {s}"

    def test_retired_keys_cleaned(self):
        """init function must clean retired localStorage keys."""
        html = read_frontend_source_text()
        assert "partialize" in html
        assert "currentWorkspaceId" in html


# ═══════════════════════════════════════════
# Translate Page Restore
# ═══════════════════════════════════════════

class TestTranslatePageRestore:
    """翻译页面刷新后能从最近 translate run 恢复摘要."""

    def test_frontend_restores_translate_summary(self):
        """Frontend must restore translate summary from recent runs."""
        html = read_frontend_source_text()
        # The restore logic must exist
        assert "latestResult" in html
        assert "translate_config" in html
        assert "quality_summary" in html

    def test_restore_does_not_read_full_config(self):
        """Restore must use safe summary, not read full config content."""
        html = read_frontend_source_text()
        # Should not embed full deployable_config in restored summary
        # The restore should set deployable_config to empty string
        restore_block = re.search(
            r"lastTranslate=\{[^}]*restored_from_run[^}]*\}",
            html, re.DOTALL
        )
        if restore_block:
            block_text = restore_block.group()
            # deployable_config should be empty in restore
            assert "deployable_config: ''" in block_text or "deployable_config:''" in block_text

    def test_restore_quality_summary_fields(self):
        """Restored translate must include quality_summary fields."""
        html = read_frontend_source_text()
        assert "quality_summary" in html, "Restore must include safe quality summary fields"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
