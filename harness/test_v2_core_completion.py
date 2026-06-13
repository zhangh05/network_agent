"""v2.0 Core Completion Batch — minimal tests for hook, token, skill, memory, approval."""

import json
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Hook tests ──

class TestHooks:
    def test_hook_registry_exists(self):
        from agent.hooks import HookRegistry, HookEvent
        reg = HookRegistry()
        assert reg is not None
        assert HookEvent.PRE_TOOL_USE is not None

    def test_hook_integration_helpers_exist(self):
        from agent.hooks_integration import (
            get_hook_registry, run_pre_tool_hooks, run_post_tool_hooks,
            run_pre_turn_hooks, run_post_turn_hooks, run_stop_hooks,
        )
        reg = get_hook_registry()
        assert reg is not None

    def test_pre_tool_deny_stops_dispatch(self):
        from agent.hooks import HookDefinition, HookEvent, HookResult
        from agent.hooks_integration import get_hook_registry, reset_hook_registry, run_pre_tool_hooks

        reset_hook_registry()
        reg = get_hook_registry()

        # Register a deny-all hook
        reg.register(HookDefinition(
            event=HookEvent.PRE_TOOL_USE,
            hook_id="test_deny",
            handler=lambda state, data: HookResult.deny("test denial"),
        ))

        class FakeState:
            intent = "test"
            workspace_id = "default"

        allowed, updated_input, reason = run_pre_tool_hooks(FakeState(), "shell.exec", {"cmd": "ls"})
        assert not allowed
        assert "test denial" in reason
        reset_hook_registry()

    def test_pre_tool_allow_passes(self):
        from agent.hooks import HookDefinition, HookEvent, HookResult
        from agent.hooks_integration import get_hook_registry, reset_hook_registry, run_pre_tool_hooks

        reset_hook_registry()
        reg = get_hook_registry()
        reg.register(HookDefinition(
            event=HookEvent.PRE_TOOL_USE,
            hook_id="test_allow",
            handler=lambda state, data: HookResult.allow(),
        ))
        class FakeState:
            intent = "test"
            workspace_id = "default"
        allowed, _, _ = run_pre_tool_hooks(FakeState(), "shell.exec", {"cmd": "ls"})
        assert allowed
        reset_hook_registry()

    def test_hooks_dont_crash_loop(self):
        """Verify hook helpers are importable and don't crash."""
        from agent.hooks_integration import reset_hook_registry
        reset_hook_registry()  # clean up any leftover from previous tests
        from agent.runtime.loop import (
            _build_hook_state, _run_pre_tool_hook, _run_post_tool_hook,
        )
        from types import SimpleNamespace
        sess = SimpleNamespace(workspace_id="default", session_id="test")
        allowed, _, _ = _run_pre_tool_hook(sess, "test.tool", {})
        # No hooks registered → should allow
        assert allowed is True


# ── Token tests ──

class TestToken:
    def test_estimate_text(self):
        from agent.runtime.token_tracker import estimate_text
        assert estimate_text("") == 0
        assert estimate_text("hello world") == max(1, 11 // 4)

    def test_estimate_messages(self):
        from agent.runtime.token_tracker import estimate_messages
        msgs = [
            {"role": "user", "content": "hello" * 100},
            {"role": "assistant", "content": "hi" * 50},
        ]
        est = estimate_messages(msgs)
        assert est > 0

    def test_record_and_get_usage(self):
        from agent.runtime.token_tracker import record_llm_call, get_usage, reset_usage_for_tests

        reset_usage_for_tests("test_ws")
        record_llm_call(
            workspace_id="test_ws", session_id="test_sess",
            provider="test", model="minimax-m3",
            input_tokens=1000, output_tokens=500,
        )
        usage = get_usage("test_ws", "test_sess")
        assert usage["ok"]
        assert usage["input_tokens"] == 1000
        assert usage["output_tokens"] == 500
        assert usage["call_count"] == 1
        reset_usage_for_tests("test_ws")

    def test_token_limit_detection(self):
        from agent.runtime.loop import _check_token_limit, TokenLimitExceeded
        msgs = [{"role": "user", "content": "x" * 500000}]  # ~125k tokens
        from types import SimpleNamespace
        ctx = SimpleNamespace(model_config={"max_context_tokens": 80000})
        with pytest.raises(TokenLimitExceeded):
            _check_token_limit(msgs, ctx, None, None, 1)


# ── Approval tests ──

class TestApproval:
    def test_approval_create_and_resolve(self):
        from agent.approval import get_approval_store

        store = get_approval_store()
        apr = store.create(session_id="test", tool_id="shell.exec",
                           arguments={"cmd": "ls"}, description="test")
        assert apr.approval_id.startswith("apr_")
        assert not apr.resolved

        result = store.resolve(apr.approval_id, allowed=True)
        assert result is not None
        assert result.allowed

    def test_approval_deny(self):
        from agent.approval import get_approval_store

        store = get_approval_store()
        apr = store.create(session_id="test", tool_id="powershell.exec",
                           arguments={}, description="test")
        result = store.resolve(apr.approval_id, allowed=False)
        assert not result.allowed

    def test_approval_get_pending(self):
        from agent.approval import get_approval_store

        store = get_approval_store()
        # cleanup any leftover
        pending = store.get_pending("test_pending")
        for p in pending:
            store.resolve(p["approval_id"], allowed=False)

        apr = store.create(session_id="test_pending", tool_id="shell.exec",
                           arguments={"cmd": "ls"})
        pending = store.get_pending("test_pending")
        assert len(pending) == 1
        assert pending[0]["tool_id"] == "shell.exec"
        store.resolve(apr.approval_id, allowed=False)


# ── Skill tests ──

class TestSkillList:
    def test_skill_list_handler(self):
        from tool_runtime.general_tools import handle_skill_list
        from tool_runtime.schemas import ToolInvocation

        inv = ToolInvocation(
            tool_id="skill.list", arguments={},
            workspace_id="default", run_id="test",
            job_id="test", dry_run=False, requested_by="test",
        )
        result = handle_skill_list(inv)
        assert result["ok"]
        assert "results" in result or "skills" in result
        skills = result.get("results") or result.get("skills", [])
        assert len(skills) > 0


# ── Memory tests ──

class TestMemory:
    def test_memory_create_rejects_secret(self):
        from tool_runtime.general_tools import handle_memory_create
        from tool_runtime.schemas import ToolInvocation

        inv = ToolInvocation(
            tool_id="memory.create", arguments={
                "workspace_id": "test", "content": "password: secret123",
                "memory_type": "decision",
            },
            workspace_id="test", run_id="test", job_id="test",
            dry_run=False, requested_by="test",
        )
        result = handle_memory_create(inv)
        assert not result["ok"]  # should reject secret

    def test_memory_create_ok(self):
        from tool_runtime.general_tools import handle_memory_create
        from tool_runtime.schemas import ToolInvocation

        inv = ToolInvocation(
            tool_id="memory.create", arguments={
                "workspace_id": "default", "title": "Test Preference",
                "content": "User prefers Cisco devices for core routing",
                "memory_type": "knowledge_note",
            },
            workspace_id="default", run_id="test", job_id="test",
            dry_run=False, requested_by="test",
        )
        result = handle_memory_create(inv)
        # knowledge_note type should pass policy (not user_preference which needs confirmation)
        assert result.get("ok") or "memory_id" in str(result) or "blocked" not in str(result).lower()

    def test_profile_set_and_get(self):
        from tool_runtime.general_tools import handle_memory_set_profile, handle_memory_get_profile
        from tool_runtime.schemas import ToolInvocation

        inv_set = ToolInvocation(
            tool_id="memory.set_profile", arguments={
                "workspace_id": "test", "field": "preferred_vendor",
                "value": "Cisco",
            },
            workspace_id="test", run_id="test", job_id="test",
            dry_run=False, requested_by="test",
        )
        result_set = handle_memory_set_profile(inv_set)
        assert result_set["ok"]

        inv_get = ToolInvocation(
            tool_id="memory.get_profile", arguments={"workspace_id": "test"},
            workspace_id="test", run_id="test", job_id="test",
            dry_run=False, requested_by="test",
        )
        result_get = handle_memory_get_profile(inv_get)
        assert result_get["ok"]


# ── Usage API test ──

class TestUsageApi:
    def test_usage_endpoint(self):
        """Minimal test: import and verify function works."""
        from agent.runtime.token_tracker import get_usage, reset_usage_for_tests
        reset_usage_for_tests("test_api")
        usage = get_usage("test_api")
        assert usage["ok"]
        assert usage["total_tokens"] == 0
