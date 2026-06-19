# agent/runtime/result_builder.py
"""Result construction helpers — extracted from loop.py."""

from agent.runtime.result import AgentResult
from agent.runtime.turn_persistence import persist_run_record
from agent.runtime.tool_result_utils import enrich_metadata
from agent.runtime.tool_decision import (
    build_tool_decision as _build_tool_decision,
    build_no_tool_reason as _build_no_tool_reason,
    build_partial_answer as _build_partial_answer,
)


def build_success_result(state) -> AgentResult:
    """Build and persist a successful AgentResult."""
    from agent.runtime.hook_runner import run_post_turn_hooks, run_stop_hooks

    stream_events = state.emitter.to_events()
    event_times = [
        float(e.get("timestamp", 0))
        for e in stream_events
        if isinstance(e, dict) and e.get("timestamp") is not None
    ]
    timeline_summary = {
        "node_count": max(6, len(stream_events)),
        "total_duration_ms": int((max(event_times) - min(event_times)) * 1000) if len(event_times) >= 2 else 0,
        "artifact_saved_count": sum(len(getattr(tr, "artifacts", []) or []) for tr in state.all_tool_results),
    }

    tool_decision = _build_tool_decision(state.all_tool_results, state.context)
    no_tool_reason = _build_no_tool_reason(state.all_tool_results, state.context)

    result = AgentResult(
        ok=True,
        final_response=state.final_response,
        session_id=state.session.session_id,
        turn_id=state.turn.turn_id,
        trace_id=state.context.trace_id,
        tool_calls=state.all_tool_results,
        warnings=state.turn.warnings,
        events=stream_events,
        tool_decision=tool_decision,
        no_tool_reason=no_tool_reason,
        metadata=enrich_metadata({
            "model": state.context.model_config.get("model", ""),
            "steps": state.step,
            "output_policy_ok": state.metadata.get("output_policy_ok", True),
            "timeline_summary": timeline_summary,
        }, state.context),
    )

    # Persist rollout
    try:
        if state.services and hasattr(state.services, 'audit_service') and state.services.audit_service:
            rollout = state.services.audit_service.get("rollout")
            if rollout:
                rollout.persist_turn(state.turn, result)
    except Exception:
        pass

    persist_run_record(state.session, state.turn, result, state.context)

    try:
        from agent.llm.config import record_recent_success
        record_recent_success()
    except Exception:
        pass

    run_post_turn_hooks(state.session, state.turn, state.final_response)
    run_stop_hooks(state.session)

    return result


def build_error_result(state, final_response, error_type, extra_meta,
                       tool_decision=None, no_tool_reason="") -> AgentResult:
    """Build and persist an error AgentResult."""
    err = AgentResult(
        ok=False,
        final_response=final_response,
        session_id=state.session.session_id,
        turn_id=state.turn.turn_id,
        trace_id=state.context.trace_id,
        tool_calls=state.all_tool_results,
        warnings=state.turn.warnings if hasattr(state.turn, 'warnings') else [],
        error_type=error_type,
        events=state.emitter.to_events(),
        tool_decision=tool_decision or {"needed": False, "reason": "Error occurred."},
        no_tool_reason=no_tool_reason,
        metadata=enrich_metadata(extra_meta, state.context),
    )
    persist_run_record(state.session, state.turn, err, state.context)
    return err


def build_partial_result(state, reason) -> AgentResult:
    """Build and persist a partial (max-steps-exceeded) AgentResult."""
    stream_events = state.emitter.to_events()
    _partial = AgentResult(
        ok=True,
        final_response=f"[partial] {_build_partial_answer(state.all_tool_results)}",
        session_id=state.session.session_id,
        turn_id=state.turn.turn_id,
        trace_id=state.context.trace_id,
        warnings=[f"max_steps ({state.max_steps}) reached — partial result"],
        events=stream_events,
        metadata=enrich_metadata({
            "terminal_reason": "max_steps_exceeded",
            "partial": True,
            "steps": state.max_steps,
        }, state.context),
    )
    persist_run_record(state.session, state.turn, _partial, state.context)
    return _partial


def build_blocked_result(state, reason, hook_event="pre_turn") -> AgentResult:
    """Build and persist a hook-blocked AgentResult."""
    result = AgentResult(
        ok=False,
        final_response="Turn blocked by pre-turn hook. Ask the user to review hook configuration.",
        session_id=state.session.session_id,
        turn_id=state.turn.turn_id,
        trace_id=state.context.trace_id,
        warnings=state.turn.warnings,
        tool_decision={"needed": False, "reason": "Turn blocked by pre-turn hook."},
        no_tool_reason="blocked_by_hook: Turn 被 pre-turn hook 阻止",
        metadata=enrich_metadata({
            "hook_event": hook_event,
            "hook_blocked": True,
        }, state.context),
    )
    persist_run_record(state.session, state.turn, result, state.context)
    return result
