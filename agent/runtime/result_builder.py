# agent/runtime/result_builder.py
"""Result construction helpers — extracted from loop.py."""

import logging

from agent.runtime.result import AgentResult
from agent.runtime.turn_persistence import persist_run_record
from agent.runtime.tool_result_utils import enrich_metadata
from agent.runtime.tool_decision import (
    build_tool_decision as _build_tool_decision,
    build_no_tool_reason as _build_no_tool_reason,
    build_partial_answer as _build_partial_answer,
)

logger = logging.getLogger(__name__)


def build_success_result(state) -> AgentResult:
    """Build and persist a successful AgentResult."""
    from agent.runtime.hook_runner import run_post_turn_hooks, run_stop_hooks

    state.final_response = _final_response_or_tool_summary(
        state.final_response,
        state.all_tool_results,
    )

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
        # v3.9.9: rollout persistence is best-effort; the agent
        # result is already finalized in memory.
        logger.debug("result_builder: rollout.persist_turn failed",
                     exc_info=True)

    persist_run_record(state.session, state.turn, result, state.context)

    # ── P1-A: Write per-turn Decision Report ──
    _write_decision_report(result, state)

    try:
        from agent.llm.config import record_recent_success
        record_recent_success()
    except Exception:
        # v3.9.9: rate-limit bookkeeping is non-critical for the
        # current turn; log only.
        logger.debug("result_builder: record_recent_success failed",
                     exc_info=True)

    run_post_turn_hooks(state.session, state.turn, state.final_response)
    run_stop_hooks(state.session)

    # v3.3.4: Defer finalization to caller (runs after "done" event)
    result._finalization_ctx = state.context

    return result


def _final_response_or_tool_summary(final_response, tool_calls: list) -> str:
    """Return final response, or a compact readable summary for tool-only turns."""
    text = str(final_response or "").strip()
    if text:
        return text
    calls = [c for c in list(tool_calls or []) if isinstance(c, dict)]
    if not calls:
        return ""

    total = len(calls)
    ok_count = sum(1 for c in calls if bool(c.get("ok")))
    failed = [c for c in calls if not bool(c.get("ok"))]
    lines = [
        f"工具调用已完成：共 {total} 次，成功 {ok_count} 次，失败 {len(failed)} 次。"
    ]
    for idx, call in enumerate(calls[:8], start=1):
        tool_id = str(call.get("tool_id") or "unknown")
        status = "成功" if call.get("ok") else "失败"
        summary = str(call.get("summary") or "").strip()
        if not summary:
            errors = call.get("errors") or []
            if errors:
                summary = str(errors[0])
        if not summary:
            result = call.get("result")
            if isinstance(result, dict):
                summary = str(
                    result.get("summary")
                    or result.get("message")
                    or result.get("error")
                    or ""
                ).strip()
        suffix = f"：{summary[:180]}" if summary else ""
        lines.append(f"{idx}. {tool_id} {status}{suffix}")
    if total > 8:
        lines.append(f"... 另有 {total - 8} 次工具调用已省略。")
    return "\n".join(lines)


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
    # ── P1-A: Decision report for error results ──
    _write_decision_report(err, state)
    err._finalization_ctx = state.context
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
    # ── P1-A: Decision report for partial results ──
    _write_decision_report(_partial, state)
    _partial._finalization_ctx = state.context
    return _partial


def build_blocked_result(state, reason, hook_event="pre_turn") -> AgentResult:
    """Build and persist a hook-blocked AgentResult."""
    response = (
        "Turn blocked by user prompt security hook. Remove credentials or sensitive values and retry."
        if hook_event == "user_prompt_submit"
        else "Turn blocked by pre-turn hook. Ask the user to review hook configuration."
    )
    result = AgentResult(
        ok=False,
        final_response=response,
        session_id=state.session.session_id,
        turn_id=state.turn.turn_id,
        trace_id=state.context.trace_id,
        warnings=state.turn.warnings,
        tool_decision={"needed": False, "reason": f"Turn blocked by {hook_event} hook."},
        no_tool_reason=f"blocked_by_hook: Turn 被 {hook_event} hook 阻止",
        metadata=enrich_metadata({
            "hook_event": hook_event,
            "hook_blocked": True,
            "hook_block_reason": reason,
        }, state.context),
    )
    persist_run_record(state.session, state.turn, result, state.context)
    # ── P1-A: Decision report for blocked results ──
    _write_decision_report(result, state)
    result._finalization_ctx = state.context
    return result


# ── P1-A: Decision Report generation ───────────────────────────────────

def _write_decision_report(result, state) -> None:
    """Generate and persist a per-turn Decision Report.

    Best-effort: failures are recorded as turn warnings,
    they do not cause turn failures.
    """
    try:
        ctx = getattr(state, "context", None)
        if ctx is None:
            return

        from agent.runtime.decision_report.builder import build_decision_report
        from agent.runtime.decision_report.writer import write_decision_report

        result_dict = (
            result.to_dict() if hasattr(result, "to_dict") else {}
        )

        run_id = (
            getattr(state.turn, "turn_id", "")
            or getattr(ctx, "turn_id", "")
            or getattr(ctx, "trace_id", "")
        )

        report = build_decision_report(
            run_id=run_id,
            session_id=getattr(state.session, "session_id", ""),
            workspace_id=getattr(ctx, "workspace_id", "") or "",
            context=ctx,
            result=result,
            result_dict=result_dict,
        )

        report_path = write_decision_report(report)

        # Store only the path in the run record, not the full JSON
        if report_path:
            state.metadata.setdefault("decision_report_path", report_path)
            ctx.metadata.setdefault("decision_report_path", report_path)
            _backfill_decision_report_path(
                run_id=run_id,
                workspace_id=getattr(ctx, "workspace_id", "") or "",
                report_path=report_path,
            )

    except Exception:
        import logging
        _log = logging.getLogger(__name__)
        _log.warning("decision_report_write_failed", exc_info=True)


def _backfill_decision_report_path(*, run_id: str, workspace_id: str, report_path: str) -> None:
    """Attach the sidecar report path to an already-written run record."""
    try:
        import json
        from workspace.run_store import WS_ROOT

        run_file = WS_ROOT / workspace_id / "runs" / f"{run_id}.json"
        if not run_file.is_file():
            return

        record = json.loads(run_file.read_text(encoding="utf-8"))
        metadata = record.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        metadata["decision_report_path"] = report_path
        record["metadata"] = metadata

        tmp = run_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.rename(run_file)
    except (OSError, ValueError):
        # v3.9.9: backfilling the run record with the report path
        # is best-effort — losing it is a UX nit, not a data loss.
        logger.debug("result_builder: backfill decision-report path failed",
                     exc_info=True)


def _ensure_snapshot(ctx, state) -> None:
    """Ensure ctx.metadata has runtime_state_snapshot for finalization kernels."""
    try:
        from agent.runtime.state.snapshot import RuntimeStateSnapshotter
        from agent.runtime.state.resolver import RuntimeStateResolver
        runtime_state = getattr(state, "runtime_state", None) or RuntimeStateResolver().resolve(ctx)
        RuntimeStateSnapshotter().snapshot(ctx, runtime_state)
    except Exception:
        # v3.9.9: snapshot is consumed by finalization kernels — if
        # it fails, those kernels see the absence; surface it.
        logger.debug("result_builder: state snapshot failed", exc_info=True)


def run_deferred_finalization(result: AgentResult) -> None:
    """Run finalization kernels after the result has been returned to the caller.

    v3.3.4: Moved here from build_*_result() so the WS "done" event
    can be sent before memory/observability/truth kernels block the thread.
    """
    try:
        ctx = getattr(result, "_finalization_ctx", None)
        if ctx is None:
            return
        if "runtime_state_snapshot" not in ctx.metadata:
            from agent.runtime.state.hooks import _run_finalization_kernels
            # snapshot will be handled by _run_finalization_kernels internally
        from agent.runtime.state.hooks import _run_finalization_kernels
        _run_finalization_kernels(ctx)
    except Exception:
        # v3.9.9: deferred finalization kernels are best-effort;
        # the user already got their answer.
        logger.debug("result_builder: deferred finalization kernels failed",
                     exc_info=True)
