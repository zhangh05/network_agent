# agent/runtime/observability/collector.py
"""ObservabilityCollector — gathers events from ctx.metadata into a TurnTrace."""

from __future__ import annotations

import uuid

from agent.runtime.observability.models import ObservabilityEvent, TurnTrace


class ObservabilityCollector:
    """Collect observability events from a turn's ctx.metadata."""

    def collect(self, ctx) -> TurnTrace:
        turn_id = getattr(ctx, "turn_id", "")
        session_id = getattr(ctx, "session_id", "")
        snap = ctx.metadata.get("runtime_state_snapshot") or {}
        task_id = snap.get("active_task_id", "") if isinstance(snap, dict) else ""
        step_id = snap.get("active_step_id", "") if isinstance(snap, dict) else ""

        events: list[ObservabilityEvent] = []
        events.extend(self._scene_events(ctx, turn_id))
        events.extend(self._context_events(ctx, turn_id))
        events.extend(self._task_events(ctx, turn_id, task_id, step_id))
        events.extend(self._action_events(ctx, turn_id))
        events.extend(self._output_events(ctx, turn_id))
        events.extend(self._response_events(ctx, turn_id))
        events.extend(self._memory_events(ctx, turn_id))

        warnings = list(ctx.metadata.get("runtime_state_warnings") or [])
        errors = list(ctx.metadata.get("context_errors") or [])

        trace = TurnTrace(
            turn_id=turn_id,
            session_id=session_id,
            task_id=task_id,
            step_id=step_id,
            events=events,
            warnings=warnings,
            errors=errors,
        )

        ctx.metadata["turn_trace"] = {
            "turn_id": trace.turn_id,
            "session_id": trace.session_id,
            "task_id": trace.task_id,
            "step_id": trace.step_id,
            "event_count": len(trace.events),
            "events": [
                {
                    "event_id": e.event_id,
                    "event_type": e.event_type,
                    "status": e.status,
                    "summary": e.summary[:200],
                }
                for e in trace.events
            ],
            "warnings": trace.warnings,
            "errors": trace.errors,
        }
        return trace

    def _scene_events(self, ctx, turn_id: str) -> list[ObservabilityEvent]:
        status = ctx.metadata.get("scene_decision_status", "")
        if not status:
            return []
        return [ObservabilityEvent(
            event_id=f"evt_{uuid.uuid4().hex[:8]}",
            event_type="scene",
            turn_id=turn_id,
            status=status,
            summary=f"scene_decision: {status}",
        )]

    def _context_events(self, ctx, turn_id: str) -> list[ObservabilityEvent]:
        status = ctx.metadata.get("context_status", "")
        if not status:
            return []
        return [ObservabilityEvent(
            event_id=f"evt_{uuid.uuid4().hex[:8]}",
            event_type="context",
            turn_id=turn_id,
            status=status,
            summary=f"context_build: {status}",
        )]

    def _task_events(self, ctx, turn_id: str, task_id: str, step_id: str) -> list[ObservabilityEvent]:
        signal = ctx.metadata.get("task_signal") or {}
        if not signal:
            return []
        return [ObservabilityEvent(
            event_id=f"evt_{uuid.uuid4().hex[:8]}",
            event_type="task",
            turn_id=turn_id,
            task_id=task_id,
            step_id=step_id,
            status=signal.get("kind", ""),
            summary=f"task_signal: {signal.get('kind', '')} ({signal.get('reason', '')})",
        )]

    def _action_events(self, ctx, turn_id: str) -> list[ObservabilityEvent]:
        events: list[ObservabilityEvent] = []
        trace = ctx.metadata.get("action_trace") or []
        for entry in trace:
            if not isinstance(entry, dict):
                continue
            events.append(ObservabilityEvent(
                event_id=f"evt_{uuid.uuid4().hex[:8]}",
                event_type="action",
                turn_id=turn_id,
                action_id=entry.get("action_id", ""),
                status=entry.get("status", ""),
                summary=str(entry.get("summary", ""))[:200],
            ))
        return events

    def _output_events(self, ctx, turn_id: str) -> list[ObservabilityEvent]:
        summary = ctx.metadata.get("output_summary") or {}
        if not summary:
            return []
        return [ObservabilityEvent(
            event_id=f"evt_{uuid.uuid4().hex[:8]}",
            event_type="output",
            turn_id=turn_id,
            status="ok" if summary.get("artifact_ids") else "empty",
            summary=str(summary.get("summary", ""))[:200],
        )]

    def _response_events(self, ctx, turn_id: str) -> list[ObservabilityEvent]:
        resp = ctx.metadata.get("final_response") or {}
        if not resp:
            return []
        return [ObservabilityEvent(
            event_id=f"evt_{uuid.uuid4().hex[:8]}",
            event_type="response",
            turn_id=turn_id,
            status=resp.get("response_type", ""),
            summary=f"response: {resp.get('response_type', '')}",
        )]

    def _memory_events(self, ctx, turn_id: str) -> list[ObservabilityEvent]:
        plan = ctx.metadata.get("memory_write_plan") or {}
        if not plan:
            return []
        return [ObservabilityEvent(
            event_id=f"evt_{uuid.uuid4().hex[:8]}",
            event_type="memory",
            turn_id=turn_id,
            status="planned",
            summary=f"memory_write: {plan.get('candidate_count', 0)} candidates, {plan.get('skipped_count', 0)} skipped",
        )]
