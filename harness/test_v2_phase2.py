"""v2.0 Phase 2 tests: skill.request_load, compact, memory enhancements, profile."""

import json
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestSkillRequestLoad:
    def test_existing_skill_returns_requested(self):
        from tool_runtime.general_tools import handle_skill_request_load
        from tool_runtime.schemas import ToolInvocation

        inv = ToolInvocation(
            tool_id="skill.request_load", arguments={
                "skill_name": "config_translation",
                "workspace_id": "default",
            },
            workspace_id="default", run_id="test", job_id="test",
            dry_run=False, requested_by="test",
        )
        result = handle_skill_request_load(inv)
        assert result["ok"]
        assert result.get("requested") is True
        assert "not implemented yet" in result.get("message", "")

    def test_nonexistent_skill_returns_error(self):
        from tool_runtime.general_tools import handle_skill_request_load
        from tool_runtime.schemas import ToolInvocation

        inv = ToolInvocation(
            tool_id="skill.request_load", arguments={
                "skill_name": "nonexistent_skill_xyz",
                "workspace_id": "default",
            },
            workspace_id="default", run_id="test", job_id="test",
            dry_run=False, requested_by="test",
        )
        result = handle_skill_request_load(inv)
        assert not result["ok"]
        assert "not found" in str(result.get("error", "")).lower()

    def test_no_direct_prompt_injection(self):
        """Verify skill.request_load does NOT inject into system prompt."""
        from tool_runtime.general_tools import handle_skill_request_load
        from tool_runtime.schemas import ToolInvocation

        inv = ToolInvocation(
            tool_id="skill.request_load", arguments={
                "skill_name": "config_translation",
                "workspace_id": "default",
            },
            workspace_id="default", run_id="test", job_id="test",
            dry_run=False, requested_by="test",
        )
        result = handle_skill_request_load(inv)
        # The result should NOT contain actual skill content
        content = json.dumps(result)
        assert "sensitive" not in content.lower()
        assert "system prompt" not in content.lower()


class TestContextCompact:
    def test_compact_module_importable(self):
        from agent.runtime.context_compactor import (
            estimate_context_size, compact_messages, should_compact,
            compact_tool_result_payload, compact_tool_result_content,
        )

    def test_estimate_nonzero(self):
        from agent.runtime.context_compactor import estimate_context_size
        msgs = [{"role": "user", "content": "hello" * 100}]
        est = estimate_context_size(msgs)
        assert est > 0

    def test_compact_preserves_recent(self):
        from agent.runtime.context_compactor import compact_messages
        msgs = [
            {"role": "system", "content": "You are a helpful agent."},
            {"role": "user", "content": "msg1" * 10},
            {"role": "assistant", "content": "reply1" * 10},
            {"role": "user", "content": "msg2" * 10},
            {"role": "assistant", "content": "reply2" * 10},
            {"role": "user", "content": "msg3" * 10},
            {"role": "assistant", "content": "reply3" * 10},
            {"role": "user", "content": "current message" * 5},
        ]
        compacted, meta = compact_messages(msgs, keep_recent=6)
        assert meta["compacted"]
        # System message should be preserved
        assert any("system" in str(m.get("role", "")) for m in compacted)
        # Current user message should be preserved
        assert any("current message" in str(m.get("content", "")) for m in compacted)

    def test_compact_no_current_user_loss(self):
        from agent.runtime.context_compactor import compact_messages
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "old1" * 50},
            {"role": "user", "content": "old2" * 50},
            {"role": "user", "content": "CURRENT_MSG"},
        ]
        compacted, _ = compact_messages(msgs, keep_recent=2)
        last_user = [m for m in compacted if m.get("role") == "user"]
        assert any("CURRENT_MSG" in str(m) for m in last_user)

    def test_compact_strips_secrets(self):
        from agent.runtime.context_compactor import compact_tool_result_content
        content = json.dumps({
            "ok": True, "summary": "ok",
            "password": "secret123", "api_key": "sk-abc",
            "source_config": "hostname R1",
        })
        result = compact_tool_result_content(content)
        assert "secret123" not in result
        assert "sk-abc" not in result
        assert "REDACTED" in result or "password" not in result.lower()

    def test_compact_reduces_size(self):
        from agent.runtime.context_compactor import compact_messages, estimate_context_size
        msgs = [{"role": "assistant", "content": "x" * 500}] * 20
        msgs.append({"role": "user", "content": "CURRENT_MSG"})
        original = estimate_context_size(msgs)
        compacted, meta = compact_messages(msgs, keep_recent=6)
        new_size = estimate_context_size(compacted)
        assert meta["compacted"]
        assert new_size < original

    def test_should_compact_triggers(self):
        from agent.runtime.context_compactor import should_compact
        msgs = [{"role": "user", "content": "x" * 200000}]  # ~50k tokens
        assert should_compact(msgs, max_context_tokens=80000, threshold=0.75) is False
        assert should_compact(msgs, max_context_tokens=40000, threshold=0.75) is True

    def test_tool_payload_keeps_safe_keys(self):
        from agent.runtime.context_compactor import compact_tool_result_payload
        payload = {
            "ok": True, "summary": "test", "tool_id": "test.tool",
            "source_count": 1, "manual_review_count": 0,
            "errors": [], "warnings": [], "artifacts": [{"artifact_id": "art_123"}],
            "password": "secret", "source_config": "hostname R1",
        }
        safe = compact_tool_result_payload(payload)
        assert "ok" in safe
        assert "summary" in safe
        # Forbidden keys should be redacted, not left as-is
        pw_val = safe.get("password", "")
        assert pw_val == "[REDACTED]" or "secret" not in str(pw_val).lower()
        sc_val = safe.get("source_config", "")
        assert sc_val == "[REDACTED]" or "hostname" not in str(sc_val).lower()


class TestMemoryConfirm:
    def test_create_returns_pending(self):
        from tool_runtime.general_tools import handle_memory_create
        from tool_runtime.schemas import ToolInvocation
        inv = ToolInvocation(
            tool_id="memory.create", arguments={
                "workspace_id": "default", "title": "Test Note",
                "content": "This is a test memory note",
                "memory_type": "knowledge_note",
            },
            workspace_id="default", run_id="test", job_id="test",
            dry_run=False, requested_by="test",
        )
        result = handle_memory_create(inv)
        assert result.get("ok") or "memory_id" in str(result)
        if result.get("ok"):
            assert result.get("status") == "pending_confirmation"
            assert "memory_id" in result

    def test_confirm_nonexistent_fails(self):
        from tool_runtime.general_tools import handle_memory_confirm
        from tool_runtime.schemas import ToolInvocation
        inv = ToolInvocation(
            tool_id="memory.confirm", arguments={
                "workspace_id": "default",
                "memory_id": "nonexistent_id_12345",
            },
            workspace_id="default", run_id="test", job_id="test",
            dry_run=False, requested_by="test",
        )
        result = handle_memory_confirm(inv)
        assert not result["ok"]

    def test_secret_rejected(self):
        from tool_runtime.general_tools import handle_memory_create
        from tool_runtime.schemas import ToolInvocation
        inv = ToolInvocation(
            tool_id="memory.create", arguments={
                "workspace_id": "default", "title": "Secret",
                "content": "password secret123",  # contains secret pattern
                "memory_type": "knowledge_note",
            },
            workspace_id="default", run_id="test", job_id="test",
            dry_run=False, requested_by="test",
        )
        result = handle_memory_create(inv)
        # Should block because content contains secret pattern
        assert not result.get("ok") or "blocked" in str(result).lower() or "secret" in str(result.get("error", "")).lower()


class TestProfileEnhanced:
    def test_get_returns_empty_structure(self):
        from tool_runtime.general_tools import handle_memory_get_profile
        from tool_runtime.schemas import ToolInvocation
        inv = ToolInvocation(
            tool_id="memory.get_profile", arguments={"workspace_id": "test_p2"},
            workspace_id="test_p2", run_id="test", job_id="test",
            dry_run=False, requested_by="test",
        )
        result = handle_memory_get_profile(inv)
        assert result["ok"]
        assert "explicit_preferences" in result

    def test_set_merges(self):
        from tool_runtime.general_tools import handle_memory_set_profile, handle_memory_get_profile
        from tool_runtime.schemas import ToolInvocation
        # Set first field
        inv1 = ToolInvocation(
            tool_id="memory.set_profile", arguments={
                "workspace_id": "test_p2", "field": "preferred_vendor",
                "value": "Cisco", "merge": True,
            },
            workspace_id="test_p2", run_id="test", job_id="test",
            dry_run=False, requested_by="test",
        )
        r1 = handle_memory_set_profile(inv1)
        assert r1["ok"]

        # Set second field with merge
        inv2 = ToolInvocation(
            tool_id="memory.set_profile", arguments={
                "workspace_id": "test_p2", "field": "preferred_os",
                "value": "IOS-XE", "merge": True,
            },
            workspace_id="test_p2", run_id="test", job_id="test",
            dry_run=False, requested_by="test",
        )
        r2 = handle_memory_set_profile(inv2)
        assert r2["ok"]

        # Get and verify both fields exist
        inv3 = ToolInvocation(
            tool_id="memory.get_profile", arguments={"workspace_id": "test_p2"},
            workspace_id="test_p2", run_id="test", job_id="test",
            dry_run=False, requested_by="test",
        )
        r3 = handle_memory_get_profile(inv3)
        assert r3["ok"]
        prefs = r3.get("explicit_preferences", {})
        assert prefs.get("preferred_vendor") == "Cisco"
        assert prefs.get("preferred_os") == "IOS-XE"

    def test_secret_rejected(self):
        from tool_runtime.general_tools import handle_memory_set_profile
        from tool_runtime.schemas import ToolInvocation
        inv = ToolInvocation(
            tool_id="memory.set_profile", arguments={
                "workspace_id": "test_p2", "field": "token",
                "value": "password mysecret", "merge": True,  # "password X" matches secret pattern
            },
            workspace_id="test_p2", run_id="test", job_id="test",
            dry_run=False, requested_by="test",
        )
        result = handle_memory_set_profile(inv)
        assert not result["ok"]


class TestPhase2Regression:
    def test_shell_still_requires_approval(self):
        from agent.runtime.services import default_runtime_services
        reg = default_runtime_services().tool_service.registry
        t = reg.get("shell.exec")
        assert t is not None
        assert t.risk_level == "high"
        assert t.requires_approval is True

    def test_powershell_still_requires_approval(self):
        from agent.runtime.services import default_runtime_services
        reg = default_runtime_services().tool_service.registry
        t = reg.get("powershell.exec")
        assert t is not None
        assert t.risk_level == "high"
        assert t.requires_approval is True

    def test_tool_count_not_decreased(self):
        from agent.runtime.services import default_runtime_services
        reg = default_runtime_services().tool_service.registry
        visible = reg.list_model_visible()
        assert len(visible) >= 63  # Phase 1 baseline

    def test_config_translation_still_registered(self):
        from agent.runtime.services import default_runtime_services
        reg = default_runtime_services().tool_service.registry
        t = reg.get("config_translation.translate_config")
        assert t is not None
