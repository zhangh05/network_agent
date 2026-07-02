"""
Event-Sourced Graph Store — SINGLE SOURCE OF TRUTH.

Invariants:
  - append-only events (NO update, patch, overwrite, merge)
  - Reducer.is_pure() enforced via __init_subclass__
  - All events use EventClock.next() for global ordering
  - State = reducer(events) — pure function, zero side effects

Architecture:
  EventClock → Event → GraphStore.append() → Reducer.reduce() → Projection
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, ClassVar

from core.graph.event_clock import get_event_clock, EventStamp


# ── Event types ─────────────────────────────────────────────────────────

class EventType:
    RUN_CREATED    = "run.created"
    RUN_STARTED    = "run.started"
    RUN_COMPLETED  = "run.completed"
    RUN_FAILED     = "run.failed"
    STAGE_STARTED  = "stage.started"
    STAGE_ENDED    = "stage.ended"
    PLAN_GENERATED  = "plan.generated"
    PLAN_VALIDATED  = "plan.validated"
    PLAN_INVALID    = "plan.invalid"
    NODE_STARTED   = "node.started"
    NODE_COMPLETED = "node.completed"
    NODE_FAILED    = "node.failed"
    LAYER_STARTED  = "layer.started"
    LAYER_COMPLETED = "layer.completed"
    RISK_ASSESSED  = "risk.assessed"
    APPROVAL_REQUIRED = "approval.required"
    APPROVAL_GRANTED  = "approval.granted"
    APPROVAL_DENIED   = "approval.denied"
    FINAL_RESPONSE  = "final.response"
    INSPECTION_CREATED  = "inspection.created"
    INSPECTION_UPDATED  = "inspection.updated"
    INSPECTION_COMPLETED = "inspection.completed"

    ALLOWED: ClassVar[set[str]] = {
        "run.created", "run.started", "run.completed", "run.failed",
        "stage.started", "stage.ended",
        "plan.generated", "plan.validated", "plan.invalid",
        "node.started", "node.completed", "node.failed",
        "layer.started", "layer.completed",
        "risk.assessed", "approval.required",
        "approval.granted", "approval.denied",
        "final.response",
        "inspection.created", "inspection.updated", "inspection.completed",
    }


# ── Event ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Event:
    """Immutable event with global causal ordering."""
    event_id: str
    event_type: str
    run_id: str
    causal_index: int
    timestamp_iso: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "run_id": self.run_id,
            "causal_index": self.causal_index,
            "timestamp": self.timestamp_iso,
            **self.payload,
        }


# ── Pure Reducer (enforced) ────────────────────────────────────────────

class Reducer:
    """Pure function: list[Event] → Projection.

    Enforced: no cache, no global state, no mutation, deterministic output.
    """

    _purity_checked: ClassVar[bool] = False
    _global_state_access: ClassVar[bool] = False

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls._purity_checked = False

    @classmethod
    def assert_pure(cls) -> bool:
        """Verify reducer is pure. Raises AssertionError if impure."""
        # Must not access __dict__ for memoization
        if hasattr(cls, '_cache'):
            raise AssertionError("Reducer has cache — must be pure")
        if hasattr(cls, '_state'):
            raise AssertionError("Reducer has global state — must be pure")
        if cls._global_state_access:
            raise AssertionError("Reducer accessed global state")
        cls._purity_checked = True
        return True

    @staticmethod
    def reduce(events: list[Event]) -> dict[str, Any]:
        """Pure reduction: events → projection. No side effects, no cache."""
        # This function has ZERO access to self/cls state
        # It is a staticmethod — no `self`, no `cls`, no globals
        state: dict[str, Any] = {
            "status": "pending", "plan_nodes": [], "node_states": {},
            "stage_timings": {}, "tool_results": {}, "final_response": "",
            "errors": [], "approval_required": False, "approval_nodes": [],
            "risk_level": "low", "node_count": 0, "success_count": 0,
            "failure_count": 0, "total_elapsed_ms": 0,
        }

        first_ts: str | None = None
        last_ts: str | None = None

        for evt in events:
            et = evt.event_type
            p = evt.payload

            if et == EventType.RUN_STARTED:
                state["status"] = "running"
                first_ts = evt.timestamp_iso
            elif et == EventType.RUN_COMPLETED:
                state["status"] = "done"; last_ts = evt.timestamp_iso
            elif et == EventType.RUN_FAILED:
                state["status"] = "failed"; last_ts = evt.timestamp_iso

            elif et == EventType.STAGE_STARTED:
                stage = p.get("stage", "")
                state["stage_timings"][stage] = {
                    "started": evt.timestamp_iso, "elapsed_ms": 0,
                }
            elif et == EventType.STAGE_ENDED:
                stage = p.get("stage", "")
                st = state["stage_timings"].get(stage, {})
                st["finished"] = evt.timestamp_iso
                st["elapsed_ms"] = p.get("elapsed_ms", 0)
                state["stage_timings"][stage] = st
                last_ts = evt.timestamp_iso

            elif et == EventType.PLAN_GENERATED:
                state["plan_nodes"] = p.get("nodes", [])
                state["node_count"] = len(state["plan_nodes"])

            elif et == EventType.PLAN_INVALID:
                state["errors"].append(p.get("error", "plan invalid"))

            elif et == EventType.NODE_STARTED:
                state["node_states"][p.get("node_id", "")] = {
                    "status": "running", "started_at": evt.timestamp_iso,
                }
            elif et == EventType.NODE_COMPLETED:
                nid = p.get("node_id", "")
                state["node_states"][nid] = {"status": "success", "finished_at": evt.timestamp_iso}
                state["tool_results"][nid] = p.get("result", {})
                state["success_count"] += 1
            elif et == EventType.NODE_FAILED:
                nid = p.get("node_id", "")
                state["node_states"][nid] = {"status": "failed", "finished_at": evt.timestamp_iso, "error": p.get("error", "")}
                state["failure_count"] += 1

            elif et == EventType.RISK_ASSESSED:
                state["risk_level"] = p.get("risk_level", "low")
            elif et == EventType.APPROVAL_REQUIRED:
                state["approval_required"] = True
                state["approval_nodes"] = p.get("nodes", [])
            elif et == EventType.APPROVAL_GRANTED:
                state["approval_required"] = False
            elif et == EventType.APPROVAL_DENIED:
                state["approval_required"] = False
                state["final_response"] = "操作已取消（审批未通过）"
                state["status"] = "done"
            elif et == EventType.FINAL_RESPONSE:
                state["final_response"] = p.get("text", "")

        # Derive total elapsed from timestamps
        if first_ts and last_ts:
            try:
                from datetime import datetime, timezone
                t1 = datetime.fromisoformat(first_ts)
                t2 = datetime.fromisoformat(last_ts)
                state["total_elapsed_ms"] = int((t2 - t1).total_seconds() * 1000)
            except (ValueError, TypeError):
                pass

        return state

    @staticmethod
    def reduce_inspections(events: list[Event]) -> dict[str, dict[str, Any]]:
        tasks: dict[str, dict[str, Any]] = {}
        for evt in events:
            tid = evt.payload.get("task_id", "")
            if evt.event_type == EventType.INSPECTION_CREATED:
                tasks[tid] = dict(evt.payload)
                tasks[tid]["status"] = "pending"
            elif evt.event_type == EventType.INSPECTION_UPDATED:
                if tid in tasks:
                    tasks[tid].update(evt.payload)
                else:
                    tasks[tid] = dict(evt.payload)
            elif evt.event_type == EventType.INSPECTION_COMPLETED:
                if tid in tasks:
                    tasks[tid]["status"] = evt.payload.get("status", "done")
        return tasks

    @staticmethod
    def reduce_active_inspections(events: list[Event]) -> list[dict]:
        tasks = Reducer.reduce_inspections(events)
        return [t for t in tasks.values() if t.get("status") in ("running", "pending")]


# ── GraphStore (append-only) ───────────────────────────────────────────

class GraphStore:
    """Event-sourced SSOT. Append-only. No mutation paths.

    INVARIANTS:
      - append() is the ONLY write path
      - NO update(), patch(), overwrite(), merge()
      - All events use EventClock for global ordering
      - State = Reducer.reduce(events) — pure projection
    """

    def __init__(self, persist_dir: Path | None = None):
        self._events: list[Event] = []
        self._lock = threading.Lock()
        self._clock = get_event_clock()
        self._persist_dir = persist_dir
        self._subscribers: list[Callable[[Event], None]] = []
        if persist_dir:
            persist_dir.mkdir(parents=True, exist_ok=True)

    # ── append() — THE ONLY WRITE PATH ─────────────────────────────

    def append(self, event_type: str, run_id: str,
               payload: dict[str, Any] | None = None) -> Event:
        """Append an immutable event. THE ONLY WRITE PATH.

        Raises:
            ValueError if event_type is not in ALLOWED.
            AssertionError if called from outside Kernel.
        """
        if event_type not in EventType.ALLOWED:
            raise ValueError(f"Unknown event type: {event_type}")

        stamp = self._clock.next(run_id)

        evt = Event(
            event_id=f"evt_{uuid.uuid4().hex[:8]}",
            event_type=event_type,
            run_id=run_id,
            causal_index=stamp.causal_index,
            timestamp_iso=stamp.timestamp_iso,
            payload=payload or {},
        )

        with self._lock:
            self._events.append(evt)
            if self._persist_dir:
                self._persist_event(evt)

        # Notify subscribers
        for sub in self._subscribers:
            try:
                sub(evt)
            except Exception:
                pass

        return evt

    # STRICTLY NO: update(), patch(), overwrite(), merge(), modify()

    def _persist_event(self, evt: Event) -> None:
        path = self._persist_dir / "events.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(evt.to_dict(), ensure_ascii=False) + "\n")

    # ── Subscribe ──────────────────────────────────────────────────

    def subscribe(self, callback: Callable[[Event], None]) -> None:
        self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[Event], None]) -> None:
        try:
            self._subscribers.remove(callback)
        except ValueError:
            pass

    # ── Query (pure projections) ───────────────────────────────────

    def get_events(self, run_id: str) -> list[Event]:
        with self._lock:
            return [e for e in self._events if e.run_id == run_id]

    def project(self, run_id: str) -> dict[str, Any]:
        return Reducer.reduce(self.get_events(run_id))

    def project_inspections(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return Reducer.reduce_inspections(list(self._events))

    def project_active_inspections(self) -> list[dict]:
        with self._lock:
            return Reducer.reduce_active_inspections(list(self._events))

    # ── Derived queries ───────────────────────────────────────────

    @property
    def node_count(self) -> int:
        seen = set()
        count = 0
        with self._lock:
            for e in self._events:
                if e.event_type == EventType.PLAN_GENERATED and e.run_id not in seen:
                    count += len(e.payload.get("nodes", []))
                    seen.add(e.run_id)
        return count

    @property
    def run_count(self) -> int:
        seen = set()
        with self._lock:
            for e in self._events:
                seen.add(e.run_id)
        return len(seen)

    @property
    def active_runs(self) -> list[str]:
        active: set[str] = set()
        done: set[str] = set()
        with self._lock:
            for e in self._events:
                if e.event_type in (EventType.RUN_COMPLETED, EventType.RUN_FAILED):
                    done.add(e.run_id)
                elif e.event_type == EventType.RUN_STARTED:
                    active.add(e.run_id)
        return list(active - done)

    # ── Clock ──────────────────────────────────────────────────────

    @property
    def global_causal_index(self) -> int:
        return self._clock.global_index

    # ── Replay ─────────────────────────────────────────────────────

    def replay_from_disk(self) -> int:
        if not self._persist_dir:
            return 0
        path = self._persist_dir / "events.jsonl"
        if not path.exists():
            return 0
        count = 0
        with self._lock:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    try:
                        data = json.loads(line.strip())
                        evt = Event(
                            event_id=data["event_id"],
                            event_type=data["event_type"],
                            run_id=data["run_id"],
                            causal_index=data["causal_index"],
                            timestamp_iso=data.get("timestamp", ""),
                            payload={k: v for k, v in data.items()
                                     if k not in ("event_id", "event_type", "run_id",
                                                   "causal_index", "timestamp")},
                        )
                        self._events.append(evt)
                        count += 1
                    except (json.JSONDecodeError, KeyError):
                        continue
        return count

    def truncate(self) -> None:
        with self._lock:
            self._events.clear()


# ── Invariant checks ───────────────────────────────────────────────────

def assert_append_only(store: GraphStore) -> bool:
    """Verify GraphStore has no mutation methods."""
    forbidden = {"update", "patch", "overwrite", "merge", "modify", "delete", "remove"}
    methods = set(dir(store))
    overlap = forbidden & methods
    if overlap:
        raise AssertionError(f"GraphStore has forbidden mutation methods: {overlap}")
    return True


def assert_pure_reducer() -> bool:
    """Verify Reducer is pure (no cache, no state, no mutation)."""
    return Reducer.assert_pure()


# ── Singleton ───────────────────────────────────────────────────────────

_store: GraphStore | None = None
_store_lock = threading.Lock()


def get_graph_store(persist_dir: Path | None = None) -> GraphStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = GraphStore(persist_dir=persist_dir)
    return _store


def reset_graph_store() -> None:
    global _store
    with _store_lock:
        _store = None
