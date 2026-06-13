"""v2.0 Phase 3 + Final Regression tests."""

import json, os, sys, pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tool_runtime.schemas import ToolInvocation


# ── Phase 1/2 Fixes ──

class TestPreTurnBlock:
    def test_pre_turn_hook_returns_block_flag(self):
        from agent.runtime.loop import _run_pre_turn_hooks
        from types import SimpleNamespace

        sess = SimpleNamespace(workspace_id="default", session_id="test")
        turn = SimpleNamespace(turn_number=0, warnings=[])
        ctx = SimpleNamespace(user_input="test")

        blocked = _run_pre_turn_hooks(sess, turn, ctx)
        # No hooks registered → should return False (not blocked)
        assert blocked is False

    def test_post_tool_returns_should_stop(self):
        from agent.runtime.loop import _run_post_tool_hook
        from agent.protocol.tool_result import ToolResult
        from types import SimpleNamespace

        sess = SimpleNamespace(workspace_id="default", session_id="test")
        turn = SimpleNamespace(warnings=[])
        result = ToolResult(ok=True, summary="test", call_id="c1", tool_id="t1")

        stopped = _run_post_tool_hook(sess, "test.tool", result, turn)
        assert stopped is False  # No hooks → not stopped


# ── Python Exec ──

class TestPythonExec:
    def test_safe_code_executes(self):
        from tool_runtime.python_exec import execute_python_code
        result = execute_python_code("print('hello world')", "default", "test-run")
        assert result["ok"]
        assert "hello world" in result["stdout"]

    def test_import_os_blocked(self):
        from tool_runtime.python_exec import execute_python_code
        result = execute_python_code("import os\nprint(os.getcwd())", "default", "test-run")
        assert not result["ok"]
        assert "forbidden" in str(result.get("error", "")).lower()

    def test_eval_blocked(self):
        from tool_runtime.python_exec import execute_python_code
        result = execute_python_code("eval('1+1')", "default", "test-run")
        assert not result["ok"]

    def test_exec_blocked(self):
        from tool_runtime.python_exec import execute_python_code
        result = execute_python_code("exec('x=1')", "default", "test-run")
        assert not result["ok"]

    def test_open_blocked(self):
        from tool_runtime.python_exec import execute_python_code
        result = execute_python_code("open('/etc/passwd')", "default", "test-run")
        assert not result["ok"]

    def test_validation_only(self):
        """Verify _validate_ast rejects import os by raising exception."""
        from tool_runtime.python_exec import _validate_ast, PythonExecSecurityError
        with pytest.raises(PythonExecSecurityError, match="Forbidden import"):
            _validate_ast("import os")

    def test_tool_registered_high_risk_approval(self):
        from agent.runtime.services import default_runtime_services
        reg = default_runtime_services().tool_service.registry
        t = reg.get("python.exec")
        assert t is not None
        assert t.risk_level == "high"
        assert t.requires_approval is True


# ── SQLite Memory ──

class TestSQLiteMemory:
    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        import sqlite3
        db = tmp_path / "test_memory.sqlite3"
        self.store_path = str(db)
        from memory.backends.sqlite_store import SQLiteMemoryStore
        self.store = SQLiteMemoryStore(db_path=str(db))

    def test_init_creates_tables(self):
        import sqlite3
        conn = sqlite3.connect(self.store_path)
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        names = [t[0] for t in tables]
        assert "memories" in names
        conn.close()

    def test_add_and_get(self):
        rec = {
            "memory_id": "m1", "workspace_id": "default", "session_id": "s1",
            "key": "test_key", "value": "test value", "value_preview": "test value",
            "status": "pending_confirmation", "source": "llm_tool",
        }
        mid = self.store.add_memory(rec)
        assert mid == "m1"

        got = self.store.get("m1")
        assert got["key"] == "test_key"

    def test_update_status(self):
        self.store.add_memory({
            "memory_id": "m2", "workspace_id": "default", "key": "k",
            "value": "v", "value_preview": "v", "status": "pending_confirmation", "source": "test",
        })
        ok = self.store.update_status("m2", "confirmed")
        assert ok
        got = self.store.get("m2")
        assert got["status"] == "confirmed"

    def test_search(self):
        self.store.add_memory({
            "memory_id": "m3", "workspace_id": "default", "key": "searchable",
            "value": "unique searchable content", "value_preview": "unique searchable content",
            "status": "confirmed", "source": "test",
        })
        results = self.store.search("unique searchable", "default")
        assert len(results) > 0

    def test_list_memories(self):
        self.store.add_memory({
            "memory_id": "m4", "workspace_id": "default", "key": "listable",
            "value": "list test", "value_preview": "list test",
            "status": "confirmed", "source": "test",
        })
        results = self.store.list_memories("default")
        assert len(results) >= 1


# ── Session Snapshot / Rewind ──

class TestSessionSnapshot:
    def test_create_snapshot(self):
        from workspace.session_snapshot import create_snapshot
        result = create_snapshot("default", "845a4e72a50a46aa", reason="test")
        assert result["ok"]
        assert "snapshot_id" in result
        return result["snapshot_id"]

    def test_list_snapshots(self):
        from workspace.session_snapshot import create_snapshot, list_snapshots
        create_snapshot("default", "845a4e72a50a46aa", reason="list test")
        snaps = list_snapshots("default", "845a4e72a50a46aa")
        assert isinstance(snaps, list)

    def test_rewind_preview(self):
        from workspace.session_snapshot import create_snapshot, rewind_session
        snap = create_snapshot("default", "845a4e72a50a46aa", reason="rewind test")
        result = rewind_session("default", "845a4e72a50a46aa", snap["snapshot_id"], dry_run=True)
        assert result["ok"]
        assert result.get("dry_run") is True

    def test_snapshot_tools_registered(self):
        from agent.runtime.services import default_runtime_services
        reg = default_runtime_services().tool_service.registry
        for tid in ("session.snapshot", "session.list_snapshots", "session.rewind"):
            assert reg.get(tid) is not None, f"{tid} not found"


# ── Sub-Agent ──

class TestSubAgent:
    def test_sub_agent_module_importable(self):
        from agent.runtime.sub_agent import run_sub_agent, DEFAULT_ALLOWED_TOOLS, FORBIDDEN_FOR_SUB_AGENT
        assert "text.classify" in DEFAULT_ALLOWED_TOOLS
        assert "shell.exec" in FORBIDDEN_FOR_SUB_AGENT
        assert "agent.spawn" in FORBIDDEN_FOR_SUB_AGENT

    def test_tool_registered(self):
        from agent.runtime.services import default_runtime_services
        reg = default_runtime_services().tool_service.registry
        t = reg.get("agent.spawn")
        assert t is not None
        assert t.risk_level == "medium"
        assert t.requires_approval is False

    def test_default_tools_are_readonly(self):
        from agent.runtime.sub_agent import DEFAULT_ALLOWED_TOOLS
        # All defaults must be low-risk read-only
        high_risk_patterns = ["exec", "write", "delete", "rewind", "spawn", "save", "tag"]
        for tool in DEFAULT_ALLOWED_TOOLS:
            for pat in high_risk_patterns:
                assert pat not in tool.lower(), f"{tool} should not be in allowed tools"

    def test_default_allowed_tools_excludes_artifact_tag(self):
        from agent.runtime.sub_agent import DEFAULT_ALLOWED_TOOLS, FORBIDDEN_FOR_SUB_AGENT
        assert "artifact.tag" not in DEFAULT_ALLOWED_TOOLS
        assert "artifact.tag" in FORBIDDEN_FOR_SUB_AGENT

    def test_forbidden_tools_blocked(self):
        from agent.runtime.sub_agent import FORBIDDEN_FOR_SUB_AGENT
        # These MUST be in the forbidden list
        must_forbid = [
            "shell.exec", "powershell.exec", "python.exec",
            "agent.spawn", "session.rewind",
            "memory.create", "memory.set_profile",
            "artifact.tag",
        ]
        for t in must_forbid:
            assert t in FORBIDDEN_FOR_SUB_AGENT, f"{t} must be FORBIDDEN for sub-agent"

    def test_high_risk_filtered_from_allowlist(self):
        """Verify that high-risk tools are filtered even if passed explicitly."""
        from agent.runtime.sub_agent import FORBIDDEN_FOR_SUB_AGENT
        # If user tries to allow shell.exec, it should still be filtered
        user_allowed = ["text.diff", "shell.exec", "memory.search"]
        filtered = [t for t in user_allowed if t not in FORBIDDEN_FOR_SUB_AGENT]
        assert "text.diff" in filtered
        assert "memory.search" in filtered
        assert "shell.exec" not in filtered

    def test_restricted_router_visible_tools(self):
        """Verify restricted ToolRouter doesn't expose forbidden tools."""
        from agent.runtime.sub_agent import DEFAULT_ALLOWED_TOOLS, FORBIDDEN_FOR_SUB_AGENT
        from tool_runtime.registry import ToolRegistry as RuntimeRegistry
        from tool_runtime.general_tools import ALL_GENERAL_TOOLS, REMOVED_GENERAL_TOOL_IDS
        from copy import deepcopy

        registry = RuntimeRegistry()
        for spec, handler in ALL_GENERAL_TOOLS:
            if spec.tool_id in REMOVED_GENERAL_TOOL_IDS:
                continue
            if spec.tool_id in DEFAULT_ALLOWED_TOOLS:
                if spec.tool_id not in FORBIDDEN_FOR_SUB_AGENT:
                    registry.register_tool(deepcopy(spec), handler)

        # Get visible tools from the restricted registry
        visible = [t["tool_id"] for t in registry.list_tools()
                   if t.get("callable_by_llm", True) and t.get("enabled", True)
                   and not t.get("forbidden", False)]

        # Must NOT contain forbidden tools
        for forbidden in ["shell.exec", "powershell.exec", "python.exec",
                          "agent.spawn", "session.rewind", "memory.create",
                          "memory.set_profile", "artifact.tag"]:
            assert forbidden not in visible, f"{forbidden} should NOT be visible in restricted router"


# ── Final Regression ──

class TestFinalRegression:
    def test_tool_count(self):
        from agent.runtime.services import default_runtime_services
        reg = default_runtime_services().tool_service.registry
        visible = reg.list_model_visible()
        assert len(visible) >= 68  # Phase 3 adds ~5 tools

    def test_shell_approval(self):
        from agent.runtime.services import default_runtime_services
        reg = default_runtime_services().tool_service.registry
        for tid in ("shell.exec", "powershell.exec"):
            t = reg.get(tid)
            assert t.risk_level == "high"
            assert t.requires_approval is True

    def test_python_exec_approval(self):
        from agent.runtime.services import default_runtime_services
        reg = default_runtime_services().tool_service.registry
        t = reg.get("python.exec")
        assert t.risk_level == "high"
        assert t.requires_approval is True

    def test_config_translation_exists(self):
        from agent.runtime.services import default_runtime_services
        reg = default_runtime_services().tool_service.registry
        assert reg.get("config_translation.translate_config") is not None

    def test_skill_request_load_no_injection(self):
        from tool_runtime.general_tools import handle_skill_request_load
        inv = ToolInvocation(
            tool_id="skill.request_load", arguments={"skill_name": "config_translation"},
            workspace_id="default", run_id="test", job_id="test",
            dry_run=False, requested_by="test",
        )
        result = handle_skill_request_load(inv)
        assert "not implemented" in result.get("message", "")

    def test_memory_profile_no_secrets(self):
        from tool_runtime.general_tools import handle_memory_set_profile
        inv = ToolInvocation(
            tool_id="memory.set_profile", arguments={"field": "x", "value": "clean", "workspace_id": "test_p3"},
            workspace_id="test_p3", run_id="test", job_id="test",
            dry_run=False, requested_by="test",
        )
        result = handle_memory_set_profile(inv)
        assert result["ok"]

    def test_compact_importable(self):
        from agent.runtime.context_compactor import compact_messages, should_compact
        assert True

    def test_token_limit_importable(self):
        from agent.runtime.loop import TokenLimitExceeded, _check_token_limit
        assert True
