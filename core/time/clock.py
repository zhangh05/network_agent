"""
Event-Derived Time System.

Rules:
  - NO standalone time truth
  - All time is derived from event timestamps
  - duration = diff(event_timestamps)
  - Stage durations = diff(stage_started, stage_ended)
  - Total elapsed = diff(run_started, run_completed)

Replaces:
  - StageClock.elapsed() business usage
  - sum(node_time) calculations
  - wall_clock + node_time aggregation
  - All scattered timing logic
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any


STAGE_ORDER = [
    "entry", "planner", "compile", "structural_validate",
    "semantic_validate", "risk_policy", "execute", "finalizer", "exit",
]

STAGE_DISPLAY: dict[str, str] = {
    "entry": "接收请求",
    "planner": "生成执行计划",
    "compile": "编译DAG",
    "structural_validate": "结构校验",
    "semantic_validate": "语义校验",
    "risk_policy": "风险评估",
    "execute": "执行工具",
    "finalizer": "整理最终回复",
    "exit": "完成",
}


# ── Time utilities ─────────────────────────────────────────────────────

def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def iso_diff_ms(start: str, end: str) -> int:
    """Calculate elapsed milliseconds between two ISO timestamps."""
    try:
        t1 = datetime.datetime.fromisoformat(start)
        t2 = datetime.datetime.fromisoformat(end)
        return int((t2 - t1).total_seconds() * 1000)
    except (ValueError, TypeError):
        return 0


# ── Event-derived timing projections ───────────────────────────────────

@dataclass
class StageTiming:
    stage: str
    started_at: str = ""
    finished_at: str = ""

    @property
    def elapsed_ms(self) -> int:
        if self.started_at and self.finished_at:
            return iso_diff_ms(self.started_at, self.finished_at)
        return 0


def derive_timeline(events: list[dict]) -> dict[str, Any]:
    """Derive complete timing from an event stream. Pure function.

    Input: list of event dicts (from GraphStore.get_events())
    Output: stage-level and total timings
    """
    stage_starts: dict[str, str] = {}
    stage_ends: dict[str, str] = {}
    run_start: str = ""
    run_end: str = ""

    for evt in events:
        et = evt.get("event_type", "")
        ts = evt.get("timestamp", evt.get("timestamp_iso", ""))

        if et == "run.started":
            run_start = ts
        elif et in ("run.completed", "run.failed"):
            run_end = ts
        elif et == "stage.started":
            stage = evt.get("stage", "")
            if stage:
                stage_starts[stage] = ts
        elif et == "stage.ended":
            stage = evt.get("stage", "")
            if stage:
                stage_ends[stage] = ts

    # Build per-stage timings
    stage_timings: dict[str, int] = {}
    for stage in STAGE_ORDER:
        s = stage_starts.get(stage, "")
        e = stage_ends.get(stage, "")
        if s and e:
            stage_timings[stage] = iso_diff_ms(s, e)

    # Total elapsed
    total_ms = iso_diff_ms(run_start, run_end) if run_start and run_end else 0

    # Progress — which stage is currently active
    current_stage = ""
    current_stage_display = ""
    current_stage_elapsed = 0
    for stage in STAGE_ORDER:
        if stage in stage_starts and stage not in stage_ends:
            current_stage = stage
            current_stage_display = STAGE_DISPLAY.get(stage, stage)
            current_stage_elapsed = iso_diff_ms(
                stage_starts[stage], now_iso(),
            )
            break

    return {
        "stage_timings": stage_timings,
        "total_elapsed_ms": total_ms,
        "current_stage": current_stage,
        "current_stage_display": current_stage_display,
        "current_stage_elapsed_ms": current_stage_elapsed,
    }


def derive_node_timings(events: list[dict]) -> dict[str, dict[str, Any]]:
    """Derive per-node timing from node.started → node.completed/failed events."""
    node_timings: dict[str, dict[str, Any]] = {}

    starts: dict[str, str] = {}
    for evt in events:
        et = evt.get("event_type", "")
        nid = evt.get("node_id", "")
        ts = evt.get("timestamp", evt.get("timestamp_iso", ""))
        if et == "node.started" and nid:
            starts[nid] = ts
        elif et in ("node.completed", "node.failed") and nid:
            if nid in starts:
                node_timings[nid] = {
                    "node_id": nid,
                    "started_at": starts[nid],
                    "finished_at": ts,
                    "elapsed_ms": iso_diff_ms(starts[nid], ts),
                    "status": "success" if et == "node.completed" else "failed",
                }

    return node_timings


def derive_progress(events: list[dict]) -> dict[str, Any]:
    """Derive execution progress from event sequence.

    Returns current/total counts for nodes, layers, etc.
    """
    total_nodes = 0
    completed = 0
    failed = 0
    started = 0
    current_depth = 0
    max_depth = 0

    for evt in events:
        et = evt.get("event_type", "")

        if et == "plan.generated":
            total_nodes = max(total_nodes, len(evt.get("nodes", [])))

        elif et == "node.started":
            started += 1

        elif et == "node.completed":
            completed += 1
            started = max(0, started - 1)

        elif et == "node.failed":
            failed += 1
            started = max(0, started - 1)

        elif et == "layer.started":
            current_depth = evt.get("depth", current_depth)
            max_depth = max(max_depth, current_depth)

    return {
        "total_nodes": total_nodes,
        "completed_nodes": completed,
        "failed_nodes": failed,
        "in_progress_nodes": started,
        "current_depth": current_depth,
        "max_depth": max_depth,
        "progress_pct": (
            round((completed + failed) / max(total_nodes, 1) * 100, 1)
            if total_nodes > 0 else 0
        ),
    }
