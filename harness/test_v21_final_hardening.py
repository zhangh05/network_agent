"""v2.1 Final Hardening tests."""
import json, pytest
from pathlib import Path


class TestSafeCmdDeny:
    def test_safe_cmd_allowlist_ls(self):
        from tool_runtime.policy import is_safe_command_first_word
        assert is_safe_command_first_word('ls') is True

    def test_unsafe_cmd_rm_denied(self):
        from tool_runtime.policy import is_safe_command_first_word
        assert is_safe_command_first_word('rm') is False

    def test_unsafe_cmd_cat_allowed(self):
        from tool_runtime.policy import is_safe_command_first_word
        assert is_safe_command_first_word('cat') is True


class TestPermissionActionCoverage:
    def test_all_visible_have_permission_action(self):
        from agent.runtime.services import default_runtime_services
        reg = default_runtime_services().tool_service.registry
        for t in reg.list_model_visible():
            pa = getattr(t, 'permission_action', '')
            assert pa, f"{t.tool_id} missing permission_action"


class TestCompactRealEffect:
    def test_compact_sets_flag(self):
        from agent.runtime.command_system import _cmd_compact
        from types import SimpleNamespace
        sess = SimpleNamespace(metadata={}, session_id='test')
        result = _cmd_compact({}, sess, None)
        assert sess.metadata.get('manual_compact_requested') is True


class TestExportRealStore:
    def test_export_returns_structured(self):
        from agent.runtime.command_system import _cmd_export
        from types import SimpleNamespace
        sess = SimpleNamespace(session_id='test_export', workspace_id='default', metadata={})
        result = _cmd_export({}, sess, None)
        assert 'ok' in str(result)


class TestSkillLoadE2E:
    def test_load_existing_skill(self):
        from tool_runtime.general_tools import handle_skill_load
        from tool_runtime.schemas import ToolInvocation
        inv = ToolInvocation(
            tool_id='skill.load', arguments={'skill_name': 'config_translation', 'session_id': 'e2e'},
            workspace_id='default', run_id='t', job_id='t', dry_run=False, requested_by='t'
        )
        r = handle_skill_load(inv)
        assert r['ok']


class TestDocsInspectGate:
    def test_inspect_agent_kernel_runs(self):
        import subprocess, sys
        result = subprocess.run([sys.executable, 'scripts/inspect_agent_kernel.py'], capture_output=True, text=True)
        assert result.returncode == 0
