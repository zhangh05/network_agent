"""
Event-Derived Time System — three-model split.

Three time dimensions:
  - execution_time: actual handler execution (lambda → return)
  - queue_time: waiting in queue before execution
  - wall_time: total clock time from event timestamps

Rules:
  - NO simple diff(events) — always explicit per-dimension
  - All time = derived from events, never standalone
  - Each dimension has its own derive function

Replace: diff(timestamp) → TimeModel.compute(event_stream)
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any


# ── Time model ──────────────────────────────────────────────────────────

@dataclass
class TimeModel:
    """Three-dimensional timing for a run or node."""
    execution_ms: int = 0      # handler wall time
    queue_ms: int = 0          # time spent waiting (between stages/nodes)
    wall_ms: int = 0           # clock time (event timestamps span)

    @classmethod
    def compute(cls, events: list[dict]) -> "TimeModel":
        """Compute all three time dimensions from event stream."""
        return TimeModel(
            execution_ms=derive_execution_time(events),
            queue_ms=derive_queue_time(events),
            wall_ms=derive_wall_time(events),
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "execution_ms": self.execution_ms,
            "queue_ms": self.queue_ms,
            "wall_ms": self.wall_ms,
        }

    @property
    def overhead_ms(self) -> int:
        """Time not spent executing (queue + other overhead)."""
        return self.wall_ms - self.execution_ms


@dataclass
class StageTiming:
    """Per-stage timing with three dimensions."""
    stage: str
    execution_ms: int = 0
    queue_ms: int = 0
    wall_ms: int = 0

    @property
    def overhead_pct(self) -> float:
        if self.wall_ms == 0:
            return 0.0
        return round((self.wall_ms - self.execution_ms) / self.wall_ms * 100, 1)


@dataclass
class RunTimeline:
    """Full run timing with per-stage breakdown."""
    run_id: str
    total: TimeModel = field(default_factory=TimeModel)
    stages: dict[str, StageTiming] = field(default_factory=dict)

    @classmethod
    def compute(cls, events: list[dict], run_id: str = "") -> "RunTimeline":
        stages: dict[str, StageTiming] = {}
        stage_starts: dict[str, str] = {}
        stage_ends: dict[str, str] = {}
        run_start = ""
        run_end = ""

        for evt in events:
            et = evt.get("event_type", "")
            ts = evt.get("timestamp", "")

            if et == "run.started":
                run_start = ts
            elif et in ("run.completed", "run.failed"):
                run_end = ts
            elif et == "stage.started":
                stage_starts[evt.get("stage", "")] = ts
            elif et == "stage.ended":
                stage_ends[evt.get("stage", "")] = ts

        for stage, start_ts in stage_starts.items():
            end_ts = stage_ends.get(stage, "")
            if end_ts:
                wall = _diff_ms(start_ts, end_ts)
                exec_ms = _derive_stage_execution(events, stage)
                queue = max(0, wall - exec_ms)
                stages[stage] = StageTiming(
                    stage=stage,
                    execution_ms=exec_ms,
                    queue_ms=queue,
                    wall_ms=wall,
                )

        total = TimeModel(
            execution_ms=sum(s.execution_ms for s in stages.values()),
            queue_ms=sum(s.queue_ms for s in stages.values()),
            wall_ms=_diff_ms(run_start, run_end),
        )

        return cls(run_id=run_id, total=total, stages=stages)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "total": self.total.to_dict(),
            "stages": {
                s: {
                    "stage": t.stage,
                    "execution_ms": t.execution_ms,
                    "queue_ms": t.queue_ms,
                    "wall_ms": t.wall_ms,
                    "overhead_pct": t.overhead_pct,
                }
                for s, t in self.stages.items()
            },
        }


# ── Derivation functions (pure, no side effects) ───────────────────────

def _diff_ms(start: str, end: str) -> int:
    """Milliseconds between two ISO timestamps."""
    if not start or not end:
        return 0
    try:
        t1 = datetime.datetime.fromisoformat(start)
        t2 = datetime.datetime.fromisoformat(end)
        return int((t2 - t1).total_seconds() * 1000)
    except (ValueError, TypeError):
        return 0


def derive_execution_time(events: list[dict]) -> int:
    """Sum of actual handler execution times (node latency)."""
    total = 0
    for evt in events:
        et = evt.get("event_type", "")
        if et in ("node.completed", "node.failed"):
            result = evt.get("result", {})
            total += result.get("latency_ms", 0)
    return total


def derive_queue_time(events: list[dict]) -> int:
    """Time spent waiting: wall_time - execution_time."""
    wall = derive_wall_time(events)
    exec_t = derive_execution_time(events)
    return max(0, wall - exec_t)


def derive_wall_time(events: list[dict]) -> int:
    """Clock time from first to last event."""
    first_ts = ""
    last_ts = ""
    for evt in events:
        et = evt.get("event_type", "")
        ts = evt.get("timestamp", "")
        if et == "run.started" and not first_ts:
            first_ts = ts
        if et in ("run.completed", "run.failed"):
            last_ts = ts
    return _diff_ms(first_ts, last_ts)


def _derive_stage_execution(events: list[dict], stage: str) -> int:
    """Extract execution time for a specific stage from events."""
    # For execute stage: sum node latencies
    if stage == "execute":
        return derive_execution_time(events)
    # For other stages: use elapsed_ms from stage_ended payload
    for evt in events:
        if (evt.get("event_type") == "stage.ended" and
                evt.get("stage") == stage):
            return evt.get("elapsed_ms", 0)
    return 0


# ── Progress (derived) ──────────────────────────────────────────────────

def derive_progress(events: list[dict]) -> dict[str, Any]:
    total_nodes = 0
    completed = 0
    failed = 0
    in_progress = 0

    for evt in events:
        et = evt.get("event_type", "")
        if et == "plan.generated":
            total_nodes = max(total_nodes, len(evt.get("nodes", [])))
        elif et == "node.started":
            in_progress += 1
        elif et == "node.completed":
            completed += 1; in_progress = max(0, in_progress - 1)
        elif et == "node.failed":
            failed += 1; in_progress = max(0, in_progress - 1)

    return {
        "total_nodes": total_nodes,
        "completed_nodes": completed,
        "failed_nodes": failed,
        "in_progress_nodes": in_progress,
        "progress_pct": (
            round((completed + failed) / max(total_nodes, 1) * 100, 1)
            if total_nodes > 0 else 0
        ),
    }


def derive_node_timings(events: list[dict]) -> dict[str, dict[str, Any]]:
    node_timings: dict[str, dict[str, Any]] = {}
    starts: dict[str, str] = {}
    for evt in events:
        et = evt.get("event_type", "")
        nid = evt.get("node_id", "")
        ts = evt.get("timestamp", "")
        if et == "node.started" and nid:
            starts[nid] = ts
        elif et in ("node.completed", "node.failed") and nid:
            if nid in starts:
                result = evt.get("result", {})
                node_timings[nid] = {
                    "node_id": nid,
                    "execution_ms": result.get("latency_ms", 0),
                    "wall_ms": _diff_ms(starts[nid], ts),
                    "status": "success" if et == "node.completed" else "failed",
                }
    return node_timings


# ── Display ─────────────────────────────────────────────────────────────

STAGE_ORDER = [
    "entry", "planner", "compile", "structural_validate",
    "semantic_validate", "risk_policy", "execute", "finalizer", "exit",
]

STAGE_DISPLAY: dict[str, str] = {
    "entry": "接收请求", "planner": "生成执行计划",
    "compile": "编译执行计划", "structural_validate": "结构校验",
    "semantic_validate": "语义校验", "risk_policy": "风险评估",
    "execute": "执行工具", "finalizer": "整理最终回复", "exit": "完成",
}


# ── Compatibility ───────────────────────────────────────────────────────

def derive_timeline(events: list[dict]) -> dict[str, Any]:
    """Simple timeline — backward compatibility wrapper."""
    timeline = RunTimeline.compute(events)
    stage_ms = {s: t.wall_ms for s, t in timeline.stages.items()}

    current_stage = ""
    current_display = ""
    current_elapsed = 0
    for stage in STAGE_ORDER:
        if stage in [e.get("stage", "") for e in events if e.get("event_type") == "stage.started"] and \
           stage not in [e.get("stage", "") for e in events if e.get("event_type") == "stage.ended"]:
            current_stage = stage
            current_display = STAGE_DISPLAY.get(stage, stage)
            break

    return {
        "stage_timings": stage_ms,
        "total_elapsed_ms": timeline.total.wall_ms,
        "current_stage": current_stage,
        "current_stage_display": current_display,
        "current_stage_elapsed_ms": current_elapsed,
    }
