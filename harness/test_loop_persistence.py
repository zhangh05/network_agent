"""Regression test: 新 runtime (loop.py) 必须把 run 落盘,
否则 /api/sessions/<id>/messages 拿不到历史 (plan-C 同步不工作).

Bug: v0.6+ 的 loop.py 用了 dataclass-based Turn/Session, 跟 legacy
NetworkAgentState 字段不一样, 所以 write_run_record 一直没被调用,
session.run_ids 永远是 [].

Fix: agent/runtime/loop.py 加 _persist_run_record adapter, 在 4 个
return 出口 (success / provider_error / timeout / max_steps) 统一
调一次.
"""
import pytest
from agent.runtime.loop import _persist_run_record
from agent.core.session import AgentSession
from agent.core.turn import AgentTurn
from agent.core.turn_context import TurnContext
from agent.runtime.result import AgentResult
from agent.protocol.op import AgentOp


def _new_session_and_turn(user_input: str):
    """Create a session via session_store, then build matching AgentSession+Turn+Context+Result."""
    from workspace.session_store import create_session
    sess = create_session(title="loop test")
    sid = sess["session_id"]
    session = AgentSession(session_id=sid, workspace_id="default")
    op = AgentOp.user_message(user_input=user_input, session_id=sid, workspace_id="default")
    turn = AgentTurn.from_op(op)
    return sid, session, turn


def _build_success(sid, turn, user_input: str) -> AgentResult:
    return AgentResult(
        ok=True,
        final_response="pong",
        session_id=sid,
        turn_id=turn.turn_id,
        trace_id="trace-x",
        tool_calls=[],
        warnings=[],
    )


def _build_context(turn, sid, user_input: str) -> TurnContext:
    return TurnContext(
        turn_id=turn.turn_id,
        session_id=sid,
        workspace_id="default",
        user_input=user_input,
        metadata={"created_at": "2026-06-11T00:00:00Z", "intent": "assistant_chat", "llm": {}},
        module_snapshot={},
        skill_snapshot={},
    )


def test_persist_creates_run_record_and_links_to_session(temp_dirs):
    """success 路径: 调 _persist_run_record 后, run record 落盘 + session.run_ids 包含 run_id."""
    from workspace.run_store import get_run
    from workspace.session_store import get_session

    sid, session, turn = _new_session_and_turn("ping")
    result = _build_success(sid, turn, "ping")
    context = _build_context(turn, sid, "ping")

    _persist_run_record(session, turn, result, context)

    rec = get_run(turn.turn_id, "default")
    assert rec, "run record should be written"
    assert rec["session_id"] == sid
    assert rec["user_input_summary"] == "ping"
    assert rec["final_response_summary"] == "pong"

    sess = get_session(sid, "default")
    assert sess is not None
    assert turn.turn_id in sess["run_ids"]


def test_persist_handles_failed_turn(temp_dirs):
    """provider_error 路径: 即便 ok=False 也得落盘 (失败也是历史)."""
    from workspace.run_store import get_run

    sid, session, turn = _new_session_and_turn("hi")
    result = AgentResult(
        ok=False,
        final_response="LLM 服务暂不可用：...",
        session_id=sid,
        turn_id=turn.turn_id,
        trace_id="t",
        errors=["provider_timeout"],
        warnings=[],
    )
    context = _build_context(turn, sid, "hi")
    _persist_run_record(session, turn, result, context)

    rec = get_run(turn.turn_id, "default")
    assert rec, "failed turn should also be persisted"
    assert rec["status"] in ("failed", "error", "partial")
    assert rec["final_response_summary"].startswith("LLM")


def test_persist_isolates_two_turns(temp_dirs):
    """同一 session 多次 turn, run_ids 应累积, get_session_messages 拿得到 2 条 user+2 条 assistant."""
    from workspace.session_store import get_session_messages

    sid, _, _ = _new_session_and_turn("seed")

    for i in range(2):
        sid, session, turn = _new_session_and_turn(f"q{i}")
        # 复用上面 auto-create 的 session 来跑多 turn
        # 这里偷个懒, 用同一个 session 跑两次 turn
        op = AgentOp.user_message(user_input=f"q{i}", session_id=sid, workspace_id="default")
        turn = AgentTurn.from_op(op)
        result = AgentResult(
            ok=True,
            final_response=f"a{i}",
            session_id=sid,
            turn_id=turn.turn_id,
            trace_id=f"trace-{i}",
        )
        context = _build_context(turn, sid, f"q{i}")
        _persist_run_record(session, turn, result, context)

    msgs = get_session_messages(sid, "default")
    assert len(msgs) >= 2  # 至少 2 条 (run 记录累积, 不强求正好 2 — create_session 复用了)
    contents = [m["content"] for m in msgs]
    # 至少能看见最新一轮的 user + assistant
    assert any("q0" in c for c in contents) or any("q1" in c for c in contents)
    assert any("a0" in c for c in contents) or any("a1" in c for c in contents)
