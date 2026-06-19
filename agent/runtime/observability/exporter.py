# agent/runtime/observability/exporter.py
"""ObservabilityExporter — exports TurnTrace as compact JSON."""

from __future__ import annotations

import json

from agent.runtime.observability.models import TurnTrace


class ObservabilityExporter:
    """Export a TurnTrace to compact JSON for debugging or logging."""

    def export_json(self, trace: TurnTrace) -> str:
        return json.dumps(self._to_dict(trace), ensure_ascii=False, separators=(",", ":"))

    def export_dict(self, trace: TurnTrace) -> dict:
        return self._to_dict(trace)

    @staticmethod
    def _to_dict(trace: TurnTrace) -> dict:
        return {
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
