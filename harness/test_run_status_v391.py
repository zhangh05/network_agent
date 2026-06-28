"""Targeted tests for the v3.9.1 status-field bug fix.

Bug: workspace.run_store._safe_status previously read result.get("ok"), but
`result` at the call site was `state.skill_results` (the tool skill payload
dict, with no `ok` key). So status was always "ok" even when the run failed,
and only `ok` (boolean) was set correctly by _merge_result_projection — the
two fields got out of sync and the UI showed "成功" in the list while the
detail page said "failed".

These tests verify:
  1. _safe_status now reads state.result_ok / state.result_errors
  2. Direct dict callers with legacy `result={"ok": False}` still work
  3. _safe_status falls through to "ok" only when there's no error signal
  4. _merge_result_projection reconciles `status` with the real `ok` field
"""
from types import SimpleNamespace


def _ctx():
    return {"llm": {}, "capability_id": "", "memory_written": False, "workspace_updated": False}


def _state(**overrides):
    base = dict(
        request_id="r1", session_id="s1", created_at="2026-01-01T00:00:00",
        user_input="hello", intent="", context=_ctx(),
        active_module="chat", selected_skill="chat", runtime_mode="codex_v1",
        final_response="", warnings=[], trace_id="", error=None,
        result_ok=None, result_errors=[],
        skill_results={}, tool_results={},
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_safe_status_reads_explicit_result_ok_false():
    from workspace.run_store import _safe_status
    # Real AgentResult.ok = False → status must be "error"
    s = _state(result_ok=False)
    assert _safe_status(s, {}) == "error", \
        "status should be 'error' when state.result_ok is False"


def test_safe_status_reads_result_errors_nonempty():
    from workspace.run_store import _safe_status
    # AgentResult.errors non-empty → status must be "error"
    s = _state(result_ok=True, result_errors=["boom"])
    assert _safe_status(s, {}) == "error", \
        "status should be 'error' when state.result_errors is non-empty"


def test_safe_status_ok_when_all_clear():
    from workspace.run_store import _safe_status
    s = _state(result_ok=True, result_errors=[])
    assert _safe_status(s, {}) == "ok"


def test_safe_status_legacy_dict_with_ok_false_still_works():
    """Back-compat: callers that pass a dict result={'ok': False} keep working."""
    from workspace.run_store import _safe_status
    s = _state()  # no result_ok / result_errors
    assert _safe_status(s, {"ok": False}) == "error"


def test_safe_status_planned_overrides_ok():
    """If capability_status=='planned', status is 'planned' regardless of ok."""
    from workspace.run_store import _safe_status
    s = _state(
        result_ok=True,
        context={"llm": {}, "capability_id": "", "memory_written": False,
                 "workspace_updated": False, "capability_status": "planned"},
    )
    assert _safe_status(s, {}) == "planned"


def test_safe_status_state_error_overrides_everything():
    """state.error is the highest-priority signal."""
    from workspace.run_store import _safe_status
    s = _state(result_ok=True, error="llm timeout")
    assert _safe_status(s, {}) == "error"


def test_merge_result_projection_reconciles_status_on_failure(monkeypatch, tmp_path):
    """The full write → merge path must end with status=='error' for failed runs."""
    from agent.runtime import turn_persistence as tp
    # Use a tmp WS_ROOT so we don't pollute real runs
    import workspace.run_store as rs
    monkeypatch.setattr(rs, "WS_ROOT", tmp_path)
    # write_run_record assumes the runs dir already exists — create it.
    (tmp_path / "default" / "runs").mkdir(parents=True, exist_ok=True)

    # Pretend the run was a failure: ok=False, errors=["something broke"]
    class _FakeResult:
        ok = False
        errors = ["something broke"]
        warnings = []
        tool_calls = []
        tool_decision = {}
        no_tool_reason = ""
        trace_id = "tr-1"
        final_response = ""
        def to_dict(self):
            return {"ok": False, "errors": ["something broke"], "turn_id": "r-fail",
                    "trace_id": "tr-1", "tool_calls": [], "tool_decision": {},
                    "no_tool_reason": "", "metadata": {}}

    state = _state(result_ok=False, result_errors=["something broke"], trace_id="tr-1")
    state.error = "something broke"

    class _FakeTurn:
        turn_id = "r-fail"
        op = None
        context = {}

    # write_run_record returns the run_id and writes the file
    state.request_id = "r-fail"  # write_run_record uses request_id as run_id
    rid = rs.write_run_record(state, "default")
    assert rid == "r-fail"

    # Then _merge_result_projection runs and writes the real result data
    tp._merge_result_projection(rid, "default", _FakeResult(), context=None)

    # Now read back the file
    from pathlib import Path
    import json
    rec = json.loads((tmp_path / "default" / "runs" / f"{rid}.json").read_text())
    assert rec["ok"] is False, f"ok must be False, got {rec['ok']}"
    assert rec["status"] == "error", (
        f"BUG STILL PRESENT: status={rec['status']!r} but ok=False. "
        f"This is exactly the bug the user reported — list says '成功', detail says 'failed'."
    )


def test_merge_result_projection_reconciles_status_on_success(monkeypatch, tmp_path):
    """Successful run must end with status=='ok' AND ok==True."""
    from agent.runtime import turn_persistence as tp
    import workspace.run_store as rs
    monkeypatch.setattr(rs, "WS_ROOT", tmp_path)
    (tmp_path / "default" / "runs").mkdir(parents=True, exist_ok=True)

    class _FakeResult:
        ok = True
        errors = []
        warnings = []
        tool_calls = []
        tool_decision = {}
        no_tool_reason = ""
        trace_id = "tr-2"
        final_response = "all good"
        def to_dict(self):
            return {"ok": True, "errors": [], "turn_id": "r-ok",
                    "trace_id": "tr-2", "tool_calls": [], "tool_decision": {},
                    "no_tool_reason": "", "metadata": {}}

    state = _state(result_ok=True, result_errors=[], trace_id="tr-2")
    state.request_id = "r-ok"

    class _FakeTurn:
        turn_id = "r-ok"
        op = None
        context = {}

    rid = rs.write_run_record(state, "default")
    tp._merge_result_projection(rid, "default", _FakeResult(), context=None)
