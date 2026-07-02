"""
Event-Sourced Graph Store — SINGLE SOURCE OF TRUTH.

Architecture:
  State = reducer(events)
  Events are append-only, immutable, causally ordered.
  NO direct state mutation. Every write is an event.

Replaces:
  - All scattered dict states
  - Direct graph mutation in execution
  - result_builder fake node_count
  - inspection local memory state
  - frontend local caches
"""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable


# ── Event types ─────────────────────────────────────────────────────────

class EventType:
    """All valid event types in the system."""
    # Kernel lifecycle
    RUN_CREATED    = "run.created"
    RUN_STARTED    = "run.started"
    RUN_COMPLETED  = "run.completed"
    RUN_FAILED     = "run.failed"

    # Stage transitions
    STAGE_STARTED  = "stage.started"
    STAGE_ENDED    = "stage.ended"

    # Planning
    PLAN_GENERATED  = "plan.generated"
    PLAN_VALIDATED  = "plan.validated"
    PLAN_INVALID    = "plan.invalid"

    # Execution
    NODE_STARTED   = "node.started"
    NODE_COMPLETED = "node.completed"
    NODE_FAILED    = "node.failed"
    LAYER_STARTED  = "layer.started"
    LAYER_COMPLETED = "layer.completed"

    # Risk / Approval
    RISK_ASSESSED  = "risk.assessed"
    APPROVAL_REQUIRED = "approval.required"
    APPROVAL_GRANTED  = "approval.granted"
    APPROVAL_DENIED   = "approval.denied"

    # Finalizer
    FINAL_RESPONSE  = "final.response"

    # Inspection
    INSPECTION_CREATED  = "inspection.created"
    INSPECTION_UPDATED  = "inspection.updated"
    INSPECTION_COMPLETED = "inspection.completed"

    ALLOWED: set[str] = {
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
    """An immutable, append-only event in the causal log."""
    event_id: str
    event_type: str
    run_id: str
    causal_index: int           # monotonic within run
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


# ── Reducer: State = f(events) ─────────────────────────────────────────

class Reducer:
    """Pure function: list[Event] → RunProjection.

    NO mutation. NO side effects. Input events → output projection.
    """

    @staticmethod
    def reduce(events: list[Event]) -> dict[str, Any]:
        """Build full state projection from event stream."""
        state: dict[str, Any] = {
            "status": "pending",
            "plan_nodes": [],
            "node_states": {},
            "stage_timings": {},
            "tool_results": {},
            "final_response": "",
            "errors": [],
            "approval_required": False,
            "approval_nodes": [],
            "risk_level": "low",
            # Derived counters
            "node_count": 0,
            "success_count": 0,
            "failure_count": 0,
            "total_elapsed_ms": 0,
        }

        last_ts: str | None = None
        first_ts: str | None = None

        for evt in events:
            et = evt.event_type

            if et == EventType.RUN_STARTED:
                state["status"] = "running"
                first_ts = evt.timestamp_iso

            elif et == EventType.RUN_COMPLETED:
                state["status"] = "done"
                last_ts = evt.timestamp_iso

            elif et == EventType.RUN_FAILED:
                state["status"] = "failed"
                last_ts = evt.timestamp_iso

            elif et == EventType.STAGE_STARTED:
                stage = evt.payload.get("stage", "")
                state["stage_timings"][stage] = {
                    "started": evt.timestamp_iso,
                    "elapsed_ms": 0,
                }

            elif et == EventType.STAGE_ENDED:
                stage = evt.payload.get("stage", "")
                st = state["stage_timings"].get(stage, {})
                st["finished"] = evt.timestamp_iso
                st["elapsed_ms"] = evt.payload.get("elapsed_ms", 0)
                state["stage_timings"][stage] = st
                last_ts = evt.timestamp_iso

            elif et == EventType.PLAN_GENERATED:
                state["plan_nodes"] = evt.payload.get("nodes", [])
                state["node_count"] = len(state["plan_nodes"])

            elif et == EventType.PLAN_INVALID:
                state["errors"].append(evt.payload.get("error", "plan invalid"))

            elif et == EventType.NODE_STARTED:
                nid = evt.payload.get("node_id", "")
                state["node_states"][nid] = {
                    "status": "running",
                    "started_at": evt.timestamp_iso,
                }

            elif et == EventType.NODE_COMPLETED:
                nid = evt.payload.get("node_id", "")
                state["node_states"][nid] = {
                    "status": "success",
                    "finished_at": evt.timestamp_iso,
                }
                state["tool_results"][nid] = evt.payload.get("result", {})
                state["success_count"] += 1

            elif et == EventType.NODE_FAILED:
                nid = evt.payload.get("node_id", "")
                state["node_states"][nid] = {
                    "status": "failed",
                    "finished_at": evt.timestamp_iso,
                    "error": evt.payload.get("error", ""),
                }
                state["failure_count"] += 1

            elif et == EventType.RISK_ASSESSED:
                state["risk_level"] = evt.payload.get("risk_level", "low")

            elif et == EventType.APPROVAL_REQUIRED:
                state["approval_required"] = True
                state["approval_nodes"] = evt.payload.get("nodes", [])

            elif et == EventType.APPROVAL_GRANTED:
                state["approval_required"] = False

            elif et == EventType.APPROVAL_DENIED:
                state["approval_required"] = False
                state["final_response"] = "操作已取消（审批未通过）"
                state["status"] = "done"

            elif et == EventType.FINAL_RESPONSE:
                state["final_response"] = evt.payload.get("text", "")

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
    def reduce_inspections(
        events: list[Event],
    ) -> dict[str, dict[str, Any]]:
        """Build inspection task projection."""
        tasks: dict[str, dict[str, Any]] = {}
        for evt in events:
            if evt.event_type == EventType.INSPECTION_CREATED:
                tid = evt.payload.get("task_id", "")
                tasks[tid] = dict(evt.payload)
                tasks[tid]["status"] = "pending"
            elif evt.event_type == EventType.INSPECTION_UPDATED:
                tid = evt.payload.get("task_id", "")
                if tid in tasks:
                    tasks[tid].update(evt.payload)
                else:
                    tasks[tid] = dict(evt.payload)
            elif evt.event_type == EventType.INSPECTION_COMPLETED:
                tid = evt.payload.get("task_id", "")
                if tid in tasks:
                    tasks[tid]["status"] = evt.payload.get("status", "done")
        return tasks

    @staticmethod
    def reduce_active_inspections(events: list[Event]) -> list[dict]:
        """Get currently running inspection tasks."""
        tasks = Reducer.reduce_inspections(events)
        return [
            t for t in tasks.values()
            if t.get("status") in ("running", "pending")
        ]


# ── GraphStore ──────────────────────────────────────────────────────────

class GraphStore:
    """Event-sourced SSOT.

    - Append-only event store
    - NO direct state mutation
    - State = reducer(events)
    - Thread-safe
    """

    def __init__(self, persist_dir: Path | None = None):
        self._events: list[Event] = []
        self._lock = threading.Lock()
        self._causal_counters: dict[str, int] = {}  # run_id → next causal_index
        self._persist_dir = persist_dir
        self._subscribers: list[Callable[[Event], None]] = []
        if persist_dir:
            persist_dir.mkdir(parents=True, exist_ok=True)

    # ── Append (THE ONLY write path) ─────────────────────────────

    def append(self, event_type: str, run_id: str,
               payload: dict[str, Any] | None = None) -> Event:
        """Append an immutable event. THE ONLY WAY to write state.

        Raises ValueError if event_type is not allowed.
        """
        if event_type not in EventType.ALLOWED:
            raise ValueError(f"Unknown event type: {event_type}")

        from core.time.clock import now_iso

        with self._lock:
            idx = self._causal_counters.get(run_id, 0)
            self._causal_counters[run_id] = idx + 1

            evt = Event(
                event_id=f"evt_{uuid.uuid4().hex[:8]}",
                event_type=event_type,
                run_id=run_id,
                causal_index=idx,
                timestamp_iso=now_iso(),
                payload=payload or {},
            )
            self._events.append(evt)

            # Persist to disk
            if self._persist_dir:
                self._persist_event(evt)

        # Notify subscribers
        for sub in self._subscribers:
            try:
                sub(evt)
            except Exception:
                pass

        return evt

    def _persist_event(self, evt: Event) -> None:
        path = self._persist_dir / "events.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(evt.to_dict(), ensure_ascii=False) + "\n")

    # ── Subscribe (reactive updates) ─────────────────────────────

    def subscribe(self, callback: Callable[[Event], None]) -> None:
        self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[Event], None]) -> None:
        try:
            self._subscribers.remove(callback)
        except ValueError:
            pass

    # ── Query (derive state from events) ─────────────────────────

    def get_events(self, run_id: str) -> list[Event]:
        """Get all events for a run, causally ordered."""
        with self._lock:
            return [e for e in self._events if e.run_id == run_id]

    def project(self, run_id: str) -> dict[str, Any]:
        """Derive full state projection for a run."""
        events = self.get_events(run_id)
        return Reducer.reduce(events)

    def project_active(self, run_id: str) -> dict[str, Any]:
        """Lightweight projection for active runs (incomplete state)."""
        return self.project(run_id)

    def project_inspections(self) -> dict[str, dict[str, Any]]:
        """Derive inspection task states."""
        with self._lock:
            return Reducer.reduce_inspections(self._events)

    def project_active_inspections(self) -> list[dict]:
        """Get currently active inspection tasks."""
        with self._lock:
            return Reducer.reduce_active_inspections(self._events)

    # ── Derived queries (truth from events, never cached) ───────

    @property
    def node_count(self) -> int:
        """Real node count from plan_generated events. Never padded."""
        count = 0
        seen = set()
        with self._lock:
            for e in self._events:
                if e.event_type == EventType.PLAN_GENERATED and e.run_id not in seen:
                    count += len(e.payload.get("nodes", []))
                    seen.add(e.run_id)
        return count

    @property
    def execution_count(self) -> int:
        """Count of nodes that actually executed."""
        count = 0
        with self._lock:
            for e in self._events:
                if e.event_type in (EventType.NODE_STARTED, EventType.NODE_COMPLETED, EventType.NODE_FAILED):
                    count += 1
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
        """Run IDs that are not yet completed/failed."""
        active: set[str] = set()
        done: set[str] = set()
        with self._lock:
            for e in self._events:
                if e.event_type in (EventType.RUN_COMPLETED, EventType.RUN_FAILED):
                    done.add(e.run_id)
                elif e.event_type == EventType.RUN_STARTED:
                    active.add(e.run_id)
        return list(active - done)

    # ── Replay / reload ──────────────────────────────────────────

    def replay_from_disk(self) -> int:
        """Reload events from persistent JSONL log. Returns count."""
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
                            timestamp_iso=data.get("timestamp", data.get("timestamp_iso", "")),
                            payload={k: v for k, v in data.items()
                                     if k not in ("event_id", "event_type", "run_id",
                                                   "causal_index", "timestamp")},
                        )
                        rid = evt.run_id
                        current = self._causal_counters.get(rid, 0)
                        self._causal_counters[rid] = max(current, evt.causal_index + 1)
                        self._events.append(evt)
                        count += 1
                    except (json.JSONDecodeError, KeyError):
                        continue
        return count

    # ── Truncate (for testing) ───────────────────────────────────

    def truncate(self) -> None:
        with self._lock:
            self._events.clear()
            self._causal_counters.clear()


# ── Singleton ───────────────────────────────────────────────────────────

_store: GraphStore | None = None


def get_graph_store(persist_dir: Path | None = None) -> GraphStore:
    global _store
    if _store is None:
        _store = GraphStore(persist_dir=persist_dir)
    return _store


def reset_graph_store() -> None:
    global _store
    _store = None
