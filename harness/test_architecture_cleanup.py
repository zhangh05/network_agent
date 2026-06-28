"""Architecture cleanup regression tests.

Validates the structural boundaries established by the architecture cleanup
branch without making real LLM calls or starting servers.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest


# ── A. SessionManager ────────────────────────────────────────────────

class TestSessionManager:
    def test_import(self):
        from agent.app.session_manager import SessionManager
        assert SessionManager is not None

    def test_agentapp_has_session_manager(self):
        from agent.app.facade import AgentApp
        app = AgentApp(services=SimpleNamespace())
        assert hasattr(app, "session_manager")

    def test_agentapp_has_inspect_sessions(self):
        from agent.app.facade import AgentApp
        app = AgentApp(services=SimpleNamespace())
        assert hasattr(app, "inspect_sessions")
        snap = app.inspect_sessions()
        assert isinstance(snap, dict)
        assert "session_count" in snap

    def test_session_manager_get_or_create(self):
        from agent.app.session_manager import SessionManager
        mgr = SessionManager(services=SimpleNamespace())
        sid, session, lock = mgr.get_or_create(None, "default")
        assert sid.startswith("session_")
        assert session is not None
        assert isinstance(lock, type(threading.RLock()))

    def test_session_manager_reuse(self):
        from agent.app.session_manager import SessionManager
        mgr = SessionManager(services=SimpleNamespace())
        sid1, s1, _ = mgr.get_or_create("test-reuse", "default")
        sid2, s2, _ = mgr.get_or_create("test-reuse", "default")
        assert sid1 == sid2
        assert s1 is s2


# ── B. context_history helper ────────────────────────────────────────

class TestContextHistoryHelper:
    def test_hydrate_importable(self):
        from agent.runtime.context_history import hydrate_history_from_store
        assert callable(hydrate_history_from_store)

    def test_loop_uses_helper(self):
        # After pipeline refactor, hydrate is called in stages/context.py
        # (delegated from loop.py via runner.py -> ContextStage).
        from pathlib import Path
        ctx_text = Path("agent/runtime/stages/context.py").read_text(encoding="utf-8")
        assert "hydrate_history_from_store" in ctx_text

    def test_loop_does_not_inline_store(self):
        text = Path("agent/runtime/loop.py").read_text(encoding="utf-8")
        assert "from workspace.message_store import SessionMessageStore" not in text

    def test_tool_adapter_has_no_system_prompt_tool_catalog(self):
        text = Path("agent/llm/tool_adapter.py").read_text(encoding="utf-8")
        assert "build_system_prompt_with_tools" not in text
        assert "Tool Usage Rules" not in text


# ── C. Permission DENY terminal ──────────────────────────────────────

class TestPermissionDenyTerminal:
    def _check(self, monkeypatch, matrix_decision):
        from agent.runtime.permission_check import check_tool_permission
        from agent.runtime.permission_matrix import PermissionDecision

        class FakePM:
            def check(self, *a, **kw):
                return matrix_decision

        monkeypatch.setattr("agent.runtime.permission_check.PermissionMatrix", FakePM)

        spec = SimpleNamespace(
            risk_level="high",
            permission_action="exec",
            requires_approval=True,
        )
        turn = SimpleNamespace(warnings=[])
        return check_tool_permission("exec.run", spec, {}, turn)

    def test_deny_is_terminal(self, monkeypatch):
        from agent.runtime.permission_matrix import PermissionDecision
        requires_approval, denied, decision = self._check(monkeypatch, PermissionDecision.DENY)
        assert denied is True
        assert requires_approval is False
        assert decision == PermissionDecision.DENY

    def test_require_approval_still_works(self, monkeypatch):
        from agent.runtime.permission_matrix import PermissionDecision
        requires_approval, denied, decision = self._check(monkeypatch, PermissionDecision.REQUIRE_APPROVAL)
        assert requires_approval is True
        assert denied is False

    def test_allow_passes_through(self, monkeypatch):
        from agent.runtime.permission_matrix import PermissionDecision
        requires_approval, denied, decision = self._check(monkeypatch, PermissionDecision.ALLOW)
        assert requires_approval is False
        assert denied is False


# ── D. agent_contract ────────────────────────────────────────────────

class TestAgentContract:
    def test_import(self):
        from backend.api.agent_contract import (
            metadata_size,
            resolve_stream_mode,
            normalize_metadata,
            normalize_agent_result,
        )
        assert all(callable(f) for f in [metadata_size, resolve_stream_mode, normalize_metadata, normalize_agent_result])

    def test_stream_bool_is_ignored(self):
        from backend.api.agent_contract import resolve_stream_mode
        enabled, mode = resolve_stream_mode({"stream": True})
        assert enabled is False
        assert mode == "sync"

    def test_stream_live_degrades_to_event_replay(self):
        from backend.api.agent_contract import resolve_stream_mode
        enabled, mode = resolve_stream_mode({"stream_mode": "live"})
        assert enabled is True
        assert mode == "event_replay"

    def test_missing_stream_mode_is_sync(self):
        from backend.api.agent_contract import resolve_stream_mode
        enabled, mode = resolve_stream_mode({"stream": False})
        assert enabled is False
        assert mode == "sync"

    def test_normalize_metadata_http(self):
        from backend.api.agent_contract import normalize_metadata
        md = normalize_metadata({}, transport="http", stream_mode="event_replay")
        assert md["transport"] == "http"
        assert md["stream_mode"] == "event_replay"
        assert md["stream_contract"] == "event_replay_after_turn_complete"

    def test_normalize_metadata_websocket(self):
        from backend.api.agent_contract import normalize_metadata
        md = normalize_metadata({}, transport="websocket", stream_mode="live")
        assert md["transport"] == "websocket"
        assert md["stream_mode"] == "live"
        assert md["stream_contract"] == "live_stream_via_stream_emitter"

    def test_normalize_result_backfills(self):
        from backend.api.agent_contract import normalize_agent_result
        result = normalize_agent_result({}, "default")
        assert result["ok"] is True
        assert result["workspace_id"] == "default"
        assert "final_response" in result
        assert "tool_calls" in result
        assert "metadata" in result


# ── E. Tool planner policy externalization ────────────────────────────

class TestToolVisibilityPolicy:
    def test_policy_importable(self):
        from agent.runtime.tool_planning.visibility import (
            BASELINE_READ_TOOLS,
            LOCAL_OPS_TOOLS,
            scene_allows_local_ops,
            build_visibility_metadata,
        )
        assert isinstance(BASELINE_READ_TOOLS, list)
        assert isinstance(LOCAL_OPS_TOOLS, list)
        assert callable(scene_allows_local_ops)
        assert callable(build_visibility_metadata)

    def test_local_ops_true_for_host_request(self):
        from agent.runtime.tool_planning.visibility import scene_allows_local_ops
        assert scene_allows_local_ops({}, "查看本机IP") is True

    def test_local_ops_false_for_translate(self):
        from agent.runtime.tool_planning.visibility import scene_allows_local_ops
        assert scene_allows_local_ops({}, "翻译这段配置") is False

    def test_baseline_includes_read_and_web_only(self):
        """BASELINE: read/discovery + web + exec.run (always visible).
        Other local exec tools (exec.python/exec.slash/system.diagnostics)
        stay scene-gated via LOCAL_OPS_TOOLS."""
        from agent.runtime.tool_planning.visibility import BASELINE_READ_TOOLS
        assert "exec.run" in BASELINE_READ_TOOLS
        assert "web.manage" in BASELINE_READ_TOOLS

    def test_local_ops_contains_host_tools(self):
        """LOCAL_OPS_TOOLS: host tools that need scene match. v3.9.2:
        exec.run is in BASELINE_READ_TOOLS; LOCAL_OPS_TOOLS keeps
        only the scene-gated merged tool (system.manage)."""
        from agent.runtime.tool_planning.visibility import LOCAL_OPS_TOOLS
        assert "exec.run" not in LOCAL_OPS_TOOLS
        assert "system.manage" in LOCAL_OPS_TOOLS
