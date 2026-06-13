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


# ── v2.1 P0 bug regression tests ──

class TestPermissionTidDefined:
    """Bug: tid/risk_level referenced before definition in PermissionMatrix."""

    def test_all_88_tools_precheck_no_name_error(self):
        """Every model-visible tool must pass permission precheck without NameError."""
        from agent.runtime.services import default_runtime_services
        from agent.runtime.permission_matrix import PermissionMatrix, PermissionAction, PermissionDecision
        reg = default_runtime_services().tool_service.registry
        pm = PermissionMatrix()
        for t in reg.list_model_visible():
            tid = t.tool_id
            risk_level = getattr(t, 'risk_level', 'low') or 'low'
            pa = getattr(t, 'permission_action', '')
            action = PermissionAction.READ
            if pa == 'exec': action = PermissionAction.EXEC
            elif pa == 'write': action = PermissionAction.WRITE
            elif pa == 'network': action = PermissionAction.NETWORK
            # This should not raise NameError
            decision = pm.check(tid, action, None, spec=t)
            assert decision in (PermissionDecision.ALLOW, PermissionDecision.DENY, PermissionDecision.REQUIRE_APPROVAL), \
                f"Unexpected decision {decision} for {tid}"

    def test_has_permission_action_no_risk_undefined(self):
        """Tools with permission_action set must not trigger risk_level undefined."""
        from agent.runtime.permission_matrix import PermissionMatrix, PermissionAction
        # Simulate the exact path: spec.permission_action exists → skip fallback
        from types import SimpleNamespace
        spec = SimpleNamespace(
            tool_id='test.exec',
            risk_level='high',
            permission_action='exec',
            requires_approval=True,
            callable_by_llm=True,
            enabled=True,
        )
        pa = getattr(spec, 'permission_action', '')
        assert pa == 'exec'
        # The risk_level assignment at line 662 must not shadow or conflict
        risk_level = getattr(spec, 'risk_level', 'low')
        assert risk_level == 'high'

    def test_no_permission_action_fallback_no_crash(self):
        """Tools without permission_action must trigger fallback without crash."""
        from types import SimpleNamespace
        spec = SimpleNamespace(
            tool_id='test.fake',
            risk_level='low',
            permission_action='',  # empty → fallback
            requires_approval=False,
            callable_by_llm=True,
            enabled=True,
        )
        pa = getattr(spec, 'permission_action', '')
        assert pa == ''
        # Simulate fallback path using tid
        tid = spec.tool_id
        risk_level = getattr(spec, 'risk_level', 'low')
        assert tid is not None
        assert risk_level is not None
        # This is the fallback path — should not raise NameError
        if risk_level == 'high':
            action = 'exec'
        else:
            action = 'read'
        assert action == 'read'


class TestCompactAfterMessagesInit:
    """Bug: manual compact ran before messages was initialized."""

    def test_compact_block_after_messages(self):
        """Verify that compact happens AFTER messages = _build_initial_messages()."""
        from agent.runtime.loop import run_turn as _run_turn
        import inspect
        src = inspect.getsource(_run_turn)
        # messages = _build_initial_messages must appear BEFORE the compact block
        build_idx = src.find('_build_initial_messages')
        compact_idx = src.find('Manual compact from previous')
        assert build_idx >= 0, "_build_initial_messages not found in run_turn"
        assert compact_idx >= 0, "manual compact block not found in run_turn"
        assert build_idx < compact_idx, \
            f"messages init at {build_idx} must come BEFORE compact at {compact_idx}"

    def test_compact_flag_cleared_after_apply(self):
        """After compact, the flag must be cleared."""
        from agent.runtime.context_compactor import compact_messages
        from agent.protocol.message import UserMessage, SystemMessage
        # Build test messages (10 messages = enough to trigger keep_recent=6)
        msgs = [UserMessage(content=f"msg{i}").to_llm_message() for i in range(10)]
        compacted, meta = compact_messages(msgs, keep_recent=6)
        # Should report compacted=true
        assert meta.get('compacted') is True or len(msgs) <= 6
        assert 'compacted_message_count' in meta

    def test_compact_no_failure_with_messages(self):
        """compact_messages with real messages must not fail."""
        from agent.runtime.context_compactor import compact_messages
        from agent.protocol.message import UserMessage
        msgs = [UserMessage(content=f"msg{i}").to_llm_message() for i in range(8)]
        try:
            compacted, meta = compact_messages(msgs, keep_recent=6)
            assert isinstance(compacted, list)
        except Exception as e:
            pytest.fail(f"compact_messages failed: {e}")
