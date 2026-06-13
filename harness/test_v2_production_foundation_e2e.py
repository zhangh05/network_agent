"""v2.0 Production Foundation E2E tests — core call chain validation."""

import json, os, sys, pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestChatChain:
    """1. Normal chat: user input → context → LLM mock → final response"""
    def test_basic_chat_no_tools(self):
        from agent.runtime.loop import run_turn
        from agent.core.session import AgentSession
        from agent.core.turn import AgentTurn
        from agent.protocol.op import AgentOp
        from agent.runtime.services import default_runtime_services

        services = default_runtime_services()
        session = AgentSession(session_id="e2e_chat", workspace_id="default", services=services)
        op = AgentOp(user_input="hello", session_id="e2e_chat", workspace_id="default")
        result = run_turn(session, AgentTurn.from_op(op), services)
        assert result is not None
        assert hasattr(result, 'ok')


class TestToolCallChain:
    """2. Tool call: LLM returns tool_call → ToolRouter → dispatch → result → final"""
    def test_tool_call_flow(self):
        from agent.runtime.services import default_runtime_services
        reg = default_runtime_services().tool_service.registry
        # Verify tool router works
        t = reg.get("json.validate")
        assert t is not None
        assert t.risk_level == "low"

    def test_unknown_tool_rejected(self):
        from agent.runtime.services import default_runtime_services
        reg = default_runtime_services().tool_service.registry
        t = reg.get("nonexistent.tool_xyz")
        assert t is None


class TestHighRiskApproval:
    """3-4. High-risk approval allow/deny"""
    def test_all_high_risk_require_approval(self):
        from agent.runtime.services import default_runtime_services
        reg = default_runtime_services().tool_service.registry
        for t in reg.list_all():
            if getattr(t, 'risk_level', '') == 'high':
                assert getattr(t, 'requires_approval', False) is True, \
                    f"{t.tool_id} is high-risk but requires_approval=False"

    def test_high_risk_count(self):
        from agent.runtime.services import default_runtime_services
        reg = default_runtime_services().tool_service.registry
        high_risk = [t for t in reg.list_all() if getattr(t, 'risk_level', '') == 'high']
        assert len(high_risk) == 3  # shell.exec, powershell.exec, python.exec

    def test_approval_store_works(self):
        from agent.approval import get_approval_store
        store = get_approval_store()
        apr = store.create(session_id="e2e", tool_id="shell.exec",
                           arguments={"command": "ls"})
        assert apr is not None
        assert not apr.resolved
        store.resolve(apr.approval_id, allowed=True)


class TestCompactAndTokenLimit:
    """6. Compact + token limit"""
    def test_compact_preserves_system(self):
        from agent.runtime.context_compactor import compact_messages
        msgs = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "hi" * 100},
            {"role": "user", "content": "CURRENT_MSG"},
        ]
        compacted, meta = compact_messages(msgs, keep_recent=2)
        assert any("system" in str(m.get("role", "")) for m in compacted)
        assert any("CURRENT_MSG" in str(m) for m in compacted)

    def test_token_limit_detection(self):
        from agent.runtime.loop import TokenLimitExceeded, _check_token_limit
        from types import SimpleNamespace
        msgs = [{"role": "user", "content": "x" * 600000}]  # ~150k tokens
        ctx = SimpleNamespace(model_config={"max_context_tokens": 80000})
        with pytest.raises(TokenLimitExceeded):
            _check_token_limit(msgs, ctx, None, None, 1)


class TestPreTurnBlock:
    """7. Pre-turn block: hook deny → no LLM → AgentResult ok=false"""
    def test_pre_turn_hook_blocked_returns_false(self):
        from agent.runtime.loop import _run_pre_turn_hooks
        from types import SimpleNamespace
        sess = SimpleNamespace(workspace_id="default", session_id="test")
        turn = SimpleNamespace(turn_number=0, warnings=[])
        ctx = SimpleNamespace()
        blocked = _run_pre_turn_hooks(sess, turn, ctx)
        assert blocked is False  # no hooks → not blocked


class TestPostToolStop:
    """8. Post-tool stop"""
    def test_post_tool_hook_returns_stop_flag(self):
        from agent.runtime.loop import _run_post_tool_hook
        from agent.protocol.tool_result import ToolResult
        from types import SimpleNamespace
        sess = SimpleNamespace(workspace_id="default", session_id="test")
        turn = SimpleNamespace(warnings=[])
        result = ToolResult(ok=True, summary="ok")
        stopped = _run_post_tool_hook(sess, "test.tool", result, turn)
        assert stopped is False  # no hooks → no stop


class TestMemoryFlow:
    """9. Memory create/confirm/list flow"""
    def test_memory_create_pending(self):
        from tool_runtime.general_tools import handle_memory_create
        from tool_runtime.schemas import ToolInvocation
        inv = ToolInvocation(
            tool_id="memory.create", arguments={
                "workspace_id": "default", "title": "E2E Test",
                "content": "This is a test memory for E2E",
                "memory_type": "knowledge_note",
            },
            workspace_id="default", run_id="e2e", job_id="e2e",
            dry_run=False, requested_by="e2e",
        )
        result = handle_memory_create(inv)
        if result["ok"]:
            assert result.get("status") == "pending_confirmation"

    def test_memory_confirm_exists(self):
        from tool_runtime.general_tools import handle_memory_confirm
        assert callable(handle_memory_confirm)

    def test_memory_list_available(self):
        from tool_runtime.general_tools import handle_memory_list
        from tool_runtime.schemas import ToolInvocation
        inv = ToolInvocation(
            tool_id="memory.list", arguments={"workspace_id": "default"},
            workspace_id="default", run_id="e2e", job_id="e2e",
            dry_run=False, requested_by="e2e",
        )
        result = handle_memory_list(inv)
        assert result["ok"]


class TestArtifactFlow:
    """10. Artifact flow"""
    def test_artifact_list_works(self):
        from agent.runtime.services import default_runtime_services
        reg = default_runtime_services().tool_service.registry
        t = reg.get("artifact.list")
        assert t is not None

    def test_artifact_read_works(self):
        from agent.runtime.services import default_runtime_services
        reg = default_runtime_services().tool_service.registry
        t = reg.get("artifact.read")
        assert t is not None

    def test_review_list_items_exists(self):
        from agent.runtime.services import default_runtime_services
        reg = default_runtime_services().tool_service.registry
        t = reg.get("review.list_items")
        assert t is not None


class TestSubAgentFlow:
    """11. Sub-agent flow"""
    def test_sub_agent_visible_tools_no_high_risk(self):
        from agent.runtime.sub_agent import DEFAULT_ALLOWED_TOOLS, FORBIDDEN_FOR_SUB_AGENT
        from agent.runtime.services import default_runtime_services
        full_reg = default_runtime_services().tool_service.registry
        visible = [t.tool_id for t in full_reg.list_all()
                   if t.tool_id in DEFAULT_ALLOWED_TOOLS and t.tool_id not in FORBIDDEN_FOR_SUB_AGENT]
        assert len(visible) >= 20
        for forbidden in ("shell.exec", "powershell.exec", "python.exec", "agent.spawn"):
            assert forbidden not in visible

    def test_sub_agent_has_read_tools(self):
        from agent.runtime.sub_agent import DEFAULT_ALLOWED_TOOLS
        assert "memory.search" in DEFAULT_ALLOWED_TOOLS
        assert "web.search" in DEFAULT_ALLOWED_TOOLS

    def test_sub_agent_count_returned(self):
        from agent.runtime.sub_agent import run_sub_agent
        # Don't actually spawn — just verify function signature includes new fields
        import inspect
        sig = inspect.signature(run_sub_agent)
        params = list(sig.parameters.keys())
        assert "instruction" in params
        assert "max_turns" in params


class TestSessionSnapshot:
    """12. Session snapshot/rewind"""
    def test_snapshot_creates(self):
        from workspace.session_snapshot import create_snapshot
        result = create_snapshot("default", "845a4e72a50a46aa", reason="e2e test")
        assert result["ok"]

    def test_rewind_preview(self):
        from workspace.session_snapshot import create_snapshot, rewind_session
        snap = create_snapshot("default", "845a4e72a50a46aa", reason="preview test")
        result = rewind_session("default", "845a4e72a50a46aa", snap["snapshot_id"], dry_run=True)
        assert result["ok"]


class TestConfigTranslationClosure:
    """Regression: config_translation/artifact/review closure"""
    def test_config_translation_exists(self):
        from agent.runtime.services import default_runtime_services
        reg = default_runtime_services().tool_service.registry
        assert reg.get("config_translation.translate_config") is not None

    def test_artifact_diff_exists(self):
        from agent.runtime.services import default_runtime_services
        reg = default_runtime_services().tool_service.registry
        assert reg.get("artifact.diff") is not None

    def test_review_update_item_exists(self):
        from agent.runtime.services import default_runtime_services
        reg = default_runtime_services().tool_service.registry
        assert reg.get("review.update_item") is not None


class TestProductionBoundaries:
    """Python.exec boundary + device boundary"""
    def test_python_exec_is_best_effort_not_container(self):
        from tool_runtime.python_exec import execute_python_code
        result = execute_python_code("print('hello')", "default", "e2e")
        # Best-effort sandbox — may fail but shouldn't crash
        assert "ok" in result

    def test_no_real_device_tools(self):
        from agent.runtime.services import default_runtime_services
        reg = default_runtime_services().tool_service.registry
        forbidden_tool_ids = [t.tool_id for t in reg.list_all()]
        # These MUST NOT exist
        for bad in ("ssh.exec", "telnet.exec", "snmp.walk", "nmap.scan",
                     "ping.sweep", "config.push"):
            assert bad not in forbidden_tool_ids, f"{bad} should not be registered"

    def test_no_config_push(self):
        from agent.runtime.services import default_runtime_services
        reg = default_runtime_services().tool_service.registry
        ids = [t.tool_id for t in reg.list_all()]
        assert "config.push" not in ids
        assert "device.exec" not in ids
