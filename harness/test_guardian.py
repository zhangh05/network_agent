"""Guardian (v3.2.0) — approval store + audit history + SSE + sub-agent audit.

Covers:
- ApprovalStore persistence (create → resolve → JSONL row + history)
- ApprovalRouter event bus (subscriber receives created/resolved events)
- Approval history query filters
- Planner JSON parser (fenced, bare, with prose, malformed → None)
- Sub-agent run record writes a structured parent-visible audit row
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ─────────────────────────────── 1. Persistence ───────────────────────────────


def test_create_and_resolve_persists_to_jsonl(tmp_path):
    from agent import approval as approval_mod
    from agent.approval import ApprovalStore, get_event_bus

    store = ApprovalStore(persist_path=tmp_path / "approvals.jsonl")

    events_received = []

    def _on_event(event):
        events_received.append(event)

    unsubscribe = get_event_bus().subscribe(_on_event)
    try:
        req = store.create(
            session_id="sess-1", tool_id="exec.run",
            arguments={"cmd": "ls -la"},
            description="run ls", risk_level="high",
            workspace_id="ws_guard",
            metadata={"argument_source": "user"},
        )
        # pending record should be in JSONL
        text = (tmp_path / "approvals.jsonl").read_text()
        assert req.approval_id in text
        assert '"resolved": false' in text or '"resolved": null' in text or '"resolved":' in text

        # resolve
        resolved = store.resolve(req.approval_id, allowed=True, workspace_id="ws_guard", resolver="user", reason="ok")
        assert resolved is not None
        assert resolved.allowed is True

        # history contains the resolved row
        history = store.get_history(session_id="sess-1")
        assert any(h["approval_id"] == req.approval_id and h["allowed"] is True for h in history)

        # subscribers received both events
        kinds = [e.kind for e in events_received]
        assert "created" in kinds
        assert "resolved" in kinds
    finally:
        unsubscribe()


def test_timeout_auto_denies_and_writes_audit(tmp_path):
    from agent.approval import ApprovalStore

    store = ApprovalStore(persist_path=tmp_path / "approvals.jsonl")
    req = store.create("sess-2", "exec.run", {"cmd": "x"}, workspace_id="ws_timeout")

    # Short timeout → wait() should auto-deny
    allowed = store.wait(req.approval_id, timeout=1.0)
    assert allowed is False

    history = store.get_history(session_id="sess-2")
    assert any(h["approval_id"] == req.approval_id and h["allowed"] is False and h["resolver"] == "system_timeout" for h in history)


def test_history_filters_by_tool_and_session(tmp_path):
    from agent.approval import ApprovalStore

    store = ApprovalStore(persist_path=tmp_path / "approvals.jsonl")
    r1 = store.create("sA", "exec.run", {"cmd": "a"}, workspace_id="ws_hist")
    r2 = store.create("sA", "exec.run", {"cmd": "b"}, workspace_id="ws_hist")
    r3 = store.create("sB", "exec.run", {"cmd": "c"}, workspace_id="ws_hist")
    for r in (r1, r2, r3):
        store.resolve(r.approval_id, allowed=True, workspace_id="ws_hist")

    by_session = store.get_history(session_id="sA")
    assert {h["approval_id"] for h in by_session} == {r1.approval_id, r2.approval_id}

    by_tool = store.get_history(tool_id="exec.run")
    assert {h["approval_id"] for h in by_tool} == {r1.approval_id, r2.approval_id, r3.approval_id}


# ─────────────────────────────── 2. Reload on startup ───────────────────────────────


def test_reload_unresolved_on_startup(tmp_path):
    from agent.approval import ApprovalStore

    path = tmp_path / "approvals.jsonl"

    s1 = ApprovalStore(persist_path=path)
    req = s1.create("sess-reload", "exec.run", {"cmd": "echo"}, workspace_id="ws_reload")
    assert req.approval_id

    # Simulate restart — fresh store reads JSONL
    s2 = ApprovalStore(persist_path=path)
    pending = s2.get_pending(session_id="sess-reload")
    assert any(p["approval_id"] == req.approval_id for p in pending)


# ─────────────────────────────── 3. Planner JSON parser ───────────────────────────────


def test_planner_json_bare_array():
    from tool_runtime.general_tools.agent_tools import _parse_planner_json
    text = '[{"task": "first"}, {"task": "second"}, {"task": "third"}]'
    assert _parse_planner_json(text) == ["first", "second", "third"]


def test_planner_json_in_fenced_code_block():
    from tool_runtime.general_tools.agent_tools import _parse_planner_json
    text = "Here is the plan:\n\n```json\n[{\"task\": \"a\"}, {\"task\": \"b\"}]\n```\n\nDone."
    assert _parse_planner_json(text) == ["a", "b"]


def test_planner_json_in_prose_with_object_form():
    from tool_runtime.general_tools.agent_tools import _parse_planner_json
    text = 'I think we should split it. Plan: {"subtasks": [{"task": "x"}, {"task": "y"}]}'
    assert _parse_planner_json(text) == ["x", "y"]


def test_planner_json_malformed_returns_none():
    from tool_runtime.general_tools.agent_tools import _parse_planner_json
    assert _parse_planner_json("nothing parseable here") is None
    assert _parse_planner_json("") is None
    assert _parse_planner_json(None) is None


def test_planner_json_caps_parallel_fanout():
    from tool_runtime.general_tools.agent_tools import _parse_planner_json
    items = [{"task": f"t{i}"} for i in range(20)]
    text = json.dumps(items)
    out = _parse_planner_json(text)
    assert out is not None
    assert len(out) == 10  # capped


# ─────────────────────────────── 4. Sub-agent run record ───────────────────────────────


def test_sub_agent_run_record_written(tmp_path, monkeypatch):
    from workspace import run_store
    from workspace.manager import ensure_workspace

    ws_root = tmp_path / "workspaces"
    monkeypatch.setattr(run_store, "WS_ROOT", ws_root)

    ensure_workspace("ws_sub")

    rid = run_store.write_sub_agent_run(
        ws_id="ws_sub",
        child_session_id="sub_child_123",
        parent_run_id="run_parent_001",
        child_run_id="run_child_002",
        instruction="Summarize the file",
        ok=True,
        final_response="It says hello.",
        tool_calls_count=2,
        steps=3,
        visible_tool_ids=["web.search", "text.analyze"],
    )
    assert rid == "run_parent_001"

    path = ws_root / "ws_sub" / "runs" / "run_parent_001.json"
    assert path.is_file()
    rec = json.loads(path.read_text())
    assert rec["is_sub_agent"] is True
    assert rec["parent_run_id"] == "run_parent_001"
    assert rec["child_run_id"] == "run_child_002"
    assert rec["child_session_id"] == "sub_child_123"
    assert rec["tool_calls_count"] == 2
    assert rec["visible_tool_ids"] == ["web.search", "text.analyze"]


# ─────────────────────────────── 5. Approval timeout configurability ───────────────────────────────


def test_approval_timeout_helper_reads_env(monkeypatch):
    import agent.runtime.loop as loop_mod
    monkeypatch.setenv("APPROVAL_TIMEOUT_DEFAULT_S", "90")
    monkeypatch.setenv("APPROVAL_TIMEOUT_SUBAGENT_S", "20")
    # Reload module to pick up env vars (constants are evaluated at import time)
    import importlib
    importlib.reload(loop_mod)
    try:
        assert loop_mod._get_approval_timeout(is_sub_agent=False) == 90.0
        assert loop_mod._get_approval_timeout(is_sub_agent=True) == 20.0
    finally:
        # Reset to defaults so other tests are not affected
        monkeypatch.delenv("APPROVAL_TIMEOUT_DEFAULT_S", raising=False)
        monkeypatch.delenv("APPROVAL_TIMEOUT_SUBAGENT_S", raising=False)
        importlib.reload(loop_mod)


# ─────────────────────────────── 6. SSE endpoint registration ───────────────────────────────


def test_sse_route_is_registered():
    """The /api/agent/approvals/sse route must exist on the Flask app."""
    from backend.main import create_app
    app = create_app()
    rules = {rule.rule for rule in app.url_map.iter_rules()}
    assert "/api/agent/approvals/sse" in rules
    assert "/api/agent/approvals/history" in rules


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
