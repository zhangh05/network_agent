"""Regression tests for latest-session tool turns and follow-up routing."""


def test_tool_planning_stage_has_canonical_namespace_import():
    import agent.runtime.context_pipeline.stages as stages

    assert hasattr(stages, "TOOL_NAMESPACE")
    assert "inspection.manage" in stages.TOOL_NAMESPACE


def test_empty_final_response_falls_back_to_tool_summary():
    from agent.runtime.result_builder import _final_response_or_tool_summary

    response = _final_response_or_tool_summary("", [
        {"tool_id": "device.manage", "ok": True, "summary": "listed 6 devices"},
        {"tool_id": "web.manage", "ok": True, "summary": "found 3 documents"},
        {"tool_id": "exec.run", "ok": False, "summary": "", "errors": ["timeout"]},
    ])

    assert response
    assert "device.manage" in response
    assert "web.manage" in response
    assert "exec.run" in response
    assert "timeout" in response


def test_session_messages_backfill_missing_assistant_from_run_record():
    from agent.state import NetworkAgentState
    from workspace.message_store import SessionMessageStore
    from workspace.run_store import write_run_record
    from workspace.session_store import create_session, get_session_messages

    ws_id = "latest_session_backfill"
    session = create_session(ws_id, title="Backfill")
    session_id = session["session_id"]
    run_id = "run_missing_assistant_backfill"

    store = SessionMessageStore(session_id=session_id, ws_id=ws_id)
    store.write_message(run_id, "user", "继续")
    state = NetworkAgentState(
        request_id=run_id,
        user_input="继续",
        final_response="工具调用已完成：共 2 次，成功 2 次，失败 0 次。",
        intent="assistant_chat",
        workspace_id=ws_id,
        session_id=session_id,
    )
    write_run_record(state, ws_id)

    messages = get_session_messages(session_id, ws_id)
    ids = [m["message_id"] for m in messages]
    assert f"{run_id}:user" in ids
    assert f"{run_id}:assistant" in ids


def test_session_messages_backfill_tool_only_run_from_decision_report():
    import json
    from pathlib import Path

    from agent.state import NetworkAgentState
    from workspace.message_store import SessionMessageStore
    from workspace.run_store import write_run_record
    from workspace.session_store import ROOT, create_session, get_session_messages

    ws_id = "latest_session_decision_backfill"
    session = create_session(ws_id, title="Decision Backfill")
    session_id = session["session_id"]
    run_id = "run_tool_only_decision_backfill"

    SessionMessageStore(session_id=session_id, ws_id=ws_id).write_message(run_id, "user", "继续")
    write_run_record(
        NetworkAgentState(
            request_id=run_id,
            user_input="继续",
            final_response="",
            intent="assistant_chat",
            workspace_id=ws_id,
            session_id=session_id,
        ),
        ws_id,
    )
    decision_path = Path(ROOT) / "workspaces" / ws_id / "runs" / f"{run_id}.decision.json"
    decision_path.parent.mkdir(parents=True, exist_ok=True)
    decision_path.write_text(json.dumps({
        "tool_execution_summary": {
            "called": ["device.manage", "exec.run"],
            "succeeded": ["device.manage"],
            "failed": ["exec.run"],
        }
    }, ensure_ascii=False), encoding="utf-8")

    assistant = [
        m for m in get_session_messages(session_id, ws_id)
        if m["message_id"] == f"{run_id}:assistant"
    ][0]
    assert "device.manage" in assistant["content"]
    assert "exec.run" in assistant["content"]
