"""
StageClock — Isolated timing layer.

Replaces:
  - engine._emit_stage() timing (total time, not per-stage)
  - trace.py  sum(node_time) + wall_clock (double-counting)
  - observability/timeline.py  node_time aggregation
  - All scattered timing calculations

Rules:
  - ONLY source of timing truths
  - No other module computes elapsed time
  - Each stage has its own start clock, NOT shared t_total

Stages are:
  entry → planner → compile → validate → risk_policy →
  execute → finalizer → exit
"""

from __future__ import annotations

import time as _time
from dataclasses import dataclass, field
from typing import Any

from . import now_iso


# ── Stage definitions ───────────────────────────────────────────────

STAGE_ORDER = [
    "entry",
    "planner",
    "compile",
    "structural_validate",
    "semantic_validate",
    "risk_policy",
    "execute",
    "finalizer",
    "exit",
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


@dataclass
class StageTiming:
    """Timing for a single pipeline stage."""
    stage: str
    started_at: float = 0.0
    finished_at: float = 0.0

    @property
    def elapsed_ms(self) -> int:
        """Stage-level elapsed time, NOT total time."""
        if self.finished_at and self.started_at:
            return int((self.finished_at - self.started_at) * 1000)
        return 0

    @property
    def is_complete(self) -> bool:
        return self.finished_at > 0


@dataclass
class StageClock:
    """Isolated timing for a single run.

    Each stage measures its OWN duration, never cumulative total.
    """

    run_id: str
    stages: dict[str, StageTiming] = field(default_factory=dict)
    _current_stage: str = ""
    _run_started: float = 0.0

    @classmethod
    def start(cls, run_id: str) -> "StageClock":
        clock = cls(run_id=run_id)
        clock._run_started = _time.monotonic()
        for s in STAGE_ORDER:
            clock.stages[s] = StageTiming(stage=s)
        return clock

    def begin_stage(self, stage: str) -> None:
        if stage not in self.stages:
            self.stages[stage] = StageTiming(stage=stage)
        self.stages[stage].started_at = _time.monotonic()
        self._current_stage = stage

    def end_stage(self, stage: str) -> None:
        if stage in self.stages:
            self.stages[stage].finished_at = _time.monotonic()

    def begin_next(self, stage: str) -> None:
        """End current stage and begin the next. Atomic transition."""
        if self._current_stage and self._current_stage in self.stages:
            self.end_stage(self._current_stage)
        self.begin_stage(stage)

    # ── Queries ──────────────────────────────────────────────────

    def elapsed(self, stage: str) -> int:
        """Get elapsed ms for a specific stage. Returns 0 if not started."""
        t = self.stages.get(stage)
        if not t:
            return 0
        if t.finished_at:
            return t.elapsed_ms
        if t.started_at:
            return int((_time.monotonic() - t.started_at) * 1000)
        return 0

    def total_elapsed_ms(self) -> int:
        """Total elapsed since run started — wall clock only, NO sum of stages."""
        if self._run_started:
            return int((_time.monotonic() - self._run_started) * 1000)
        return 0

    def sum_stage_elapsed(self) -> int:
        """Sum of completed stage durations. For audit only."""
        return sum(
            t.elapsed_ms for t in self.stages.values()
            if t.is_complete
        )

    @property
    def current_stage(self) -> str:
        return self._current_stage

    @property
    def current_stage_display(self) -> str:
        return STAGE_DISPLAY.get(self._current_stage, self._current_stage)

    @property
    def current_stage_elapsed_ms(self) -> int:
        """Elapsed time of the CURRENT stage only."""
        return self.elapsed(self._current_stage)

    # ── Stage timing for emitter ──────────────────────────────────

    def stage_event(self, stage: str) -> dict[str, Any]:
        """Build a truthful stage event payload.
        
        elapsed_ms = stage-level time, NOT total time.
        """
        t = self.stages.get(stage)
        return {
            "stage": stage,
            "display": STAGE_DISPLAY.get(stage, stage),
            "elapsed_ms": self.elapsed(stage),        # per-stage
            "total_elapsed_ms": self.total_elapsed_ms(),  # wall clock
        }

    # ── Result timing ─────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "total_elapsed_ms": self.total_elapsed_ms(),
            "stage_timings": {
                s: t.elapsed_ms
                for s, t in self.stages.items()
                if t.is_complete
            },
        }


# ── Global clock registry ────────────────────────────────────────────

_clocks: dict[str, StageClock] = {}


def get_clock(run_id: str) -> StageClock | None:
    return _clocks.get(run_id)


def start_clock(run_id: str) -> StageClock:
    clock = StageClock.start(run_id)
    _clocks[run_id] = clock
    return clock


def remove_clock(run_id: str) -> None:
    _clocks.pop(run_id, None)
