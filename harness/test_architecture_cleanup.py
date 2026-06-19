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
        text = Path("agent/runtime/loop.py").read_text(encoding="utf-8")
        assert "hydrate_history_from_store" in text

    def test_loop_does_not_inline_store(self):
        text = Path("agent/runtime/loop.py").read_text(encoding="utf-8")
        assert "from workspace.message_store import SessionMessageStore" not in text


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
        return check_tool_permission("host.shell.exec", spec, {}, turn)

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

    def test_stream_true_is_event_replay(self):
        from backend.api.agent_contract import resolve_stream_mode
        enabled, mode = resolve_stream_mode({"stream": True})
        assert enabled is True
        assert mode == "event_replay"

    def test_stream_live_degrades_to_event_replay(self):
        from backend.api.agent_contract import resolve_stream_mode
        enabled, mode = resolve_stream_mode({"stream_mode": "live"})
        assert enabled is True
        assert mode == "event_replay"

    def test_stream_false_is_sync(self):
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
        from agent.runtime.tool_visibility_policy import (
            BASELINE_READ_TOOLS,
            LOCAL_OPS_TOOLS,
            scene_allows_local_ops,
            build_visibility_metadata,
        )
        assert isinstance(BASELINE_READ_TOOLS, list)
        assert isinstance(LOCAL_OPS_TOOLS, list)
        assert callable(scene_allows_local_ops)
        assert callable(build_visibility_metadata)

    def test_compat_aliases_in_planner(self):
        from agent.runtime.tool_planner import (
            _BASELINE_READ_TOOLS,
            _LOCAL_OPS_TOOLS,
            _scene_allows_local_ops,
            _visibility_metadata,
        )
        assert isinstance(_BASELINE_READ_TOOLS, list)
        assert isinstance(_LOCAL_OPS_TOOLS, list)
        assert callable(_scene_allows_local_ops)
        assert callable(_visibility_metadata)

    def test_local_ops_true_for_host_request(self):
        from agent.runtime.tool_visibility_policy import scene_allows_local_ops
        assert scene_allows_local_ops({}, "查看本机IP") is True

    def test_local_ops_false_for_translate(self):
        from agent.runtime.tool_visibility_policy import scene_allows_local_ops
        assert scene_allows_local_ops({}, "翻译这段配置") is False

    def test_baseline_no_shell(self):
        from agent.runtime.tool_visibility_policy import BASELINE_READ_TOOLS
        assert "host.shell.exec" not in BASELINE_READ_TOOLS
        assert "host.powershell.exec" not in BASELINE_READ_TOOLS
        assert "host.python.exec" not in BASELINE_READ_TOOLS

    def test_local_ops_has_shell(self):
        from agent.runtime.tool_visibility_policy import LOCAL_OPS_TOOLS
        assert "host.shell.exec" in LOCAL_OPS_TOOLS
        assert "host.powershell.exec" in LOCAL_OPS_TOOLS
        assert "host.python.exec" in LOCAL_OPS_TOOLS
