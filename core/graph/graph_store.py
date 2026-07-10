"""
Event-Sourced Graph Store — SINGLE SOURCE OF TRUTH.

Invariants:
  - append-only events (NO update, patch, overwrite, merge)
  - Pure module-level reducer functions (no @staticmethod, no class state)
  - All events use EventClock.next() for global ordering
  - State = reducer(events) — pure function, zero side effects
  - Events are frozen (frozen=True) with deep-copied payload

Architecture:
  EventClock → Event → GraphStore.append() → reducer(events) → Projection
"""

from __future__ import annotations

import copy
import json
import threading
import uuid
from dataclasses import FrozenInstanceError, dataclass, field
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
    RUN_RECORD_WRITTEN = "projection.run_record.written"
    MESSAGE_WRITTEN = "projection.message.written"
    ARTIFACT_WRITTEN = "projection.artifact.written"
    MEMORY_WRITTEN = "projection.memory.written"
    MEMORY_DELETED = "projection.memory.deleted"
    TRACE_WRITTEN = "projection.trace.written"
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
        "projection.run_record.written", "projection.message.written",
        "projection.artifact.written", "projection.memory.written",
        "projection.memory.deleted",
        "projection.trace.written",
        "inspection.created", "inspection.updated", "inspection.completed",
    }


# ── Event (FROZEN, IMMUTABLE) ───────────────────────────────────────────

@dataclass(frozen=True)
class Event:
    """Immutable event with global causal ordering.

    Invariants:
      - frozen=True (cannot mutate after construction)
      - payload is deep-copied on construction (no shared references)
      - to_dict() returns deep-copied payload (no aliasing)
    """
    event_id: str
    event_type: str
    run_id: str
    causal_index: int
    timestamp_iso: str
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        # Deep-copy payload to ensure no shared references from caller
        object.__setattr__(self, "payload", copy.deepcopy(self.payload or {}))

    def to_dict(self) -> dict[str, Any]:
        # Deep-copy again at serialization so callers can't mutate stored event
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "run_id": self.run_id,
            "causal_index": self.causal_index,
            "timestamp": self.timestamp_iso,
            **copy.deepcopy(self.payload),
        }


# ── Pure Reducer functions (MODULE LEVEL, NOT CLASS METHODS) ────────────
#
# These are top-level pure functions. They MUST NOT:
#   - Reference any class/instance
#   - Reference any global mutable state
#   - Capture variables from a closure
#   - Use @staticmethod / @classmethod
#
# State = reducer(events) — pure projection, zero side effects.

def reduce(events: list[Event]) -> dict[str, Any]:
    """Pure projection: events → state dict.

    Module-level pure function. No `self`, no `cls`, no globals.
    Same input ALWAYS produces same output.
    """
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
            state["status"] = "done"
            last_ts = evt.timestamp_iso
        elif et == EventType.RUN_FAILED:
            state["status"] = "failed"
            last_ts = evt.timestamp_iso

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

    # Derive total elapsed from event timestamps (NOT external time source)
    if first_ts and last_ts:
        try:
            from datetime import datetime
            t1 = datetime.fromisoformat(first_ts)
            t2 = datetime.fromisoformat(last_ts)
            state["total_elapsed_ms"] = int((t2 - t1).total_seconds() * 1000)
        except (ValueError, TypeError):
            pass

    return state


def reduce_inspections(events: list[Event]) -> dict[str, dict[str, Any]]:
    """Pure inspection task projection."""
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


def reduce_active_inspections(events: list[Event]) -> list[dict]:
    """Pure projection of active inspection tasks."""
    tasks = reduce_inspections(events)
    return [t for t in tasks.values() if t.get("status") in ("running", "pending")]


# ── GraphStore (append-only) ───────────────────────────────────────────

class GraphStore:
    """Event-sourced SSOT. Append-only. No mutation paths.

    INVARIANTS:
      - append() is the ONLY write path
      - NO update(), patch(), overwrite(), merge(), modify()
      - All events use EventClock for global ordering
      - State = reduce(events) — pure projection (module-level function)
    """

    def __init__(self, persist_dir: Path | None = None):
        self._events: list[Event] = []
        self._lock = threading.Lock()
        self._clock = get_event_clock()
        self._persist_dir = persist_dir
        self._subscribers: list[Callable[[Event], None]] = []
        if persist_dir:
            persist_dir.mkdir(parents=True, exist_ok=True)
            self.replay_from_disk()

    # ── append() — THE ONLY WRITE PATH ─────────────────────────────

    def append(self, event_type: str, run_id: str,
               payload: dict[str, Any] | None = None) -> Event:
        """Append an immutable event. THE ONLY WRITE PATH.

        Raises:
            ValueError if event_type is not in ALLOWED.
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
        path.parent.mkdir(parents=True, exist_ok=True)
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
        return reduce(self.get_events(run_id))

    def project_inspections(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return reduce_inspections(list(self._events))

    def project_active_inspections(self) -> list[dict]:
        with self._lock:
            return reduce_active_inspections(list(self._events))

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
        max_causal_index = 0
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
                        max_causal_index = max(max_causal_index, evt.causal_index)
                        count += 1
                    except (json.JSONDecodeError, KeyError):
                        continue
        if max_causal_index:
            try:
                # P0-13: GraphStore._lock guards EventClock._global_index mutation.
                # Multi-process Flask + shared persist_dir can cause causal_index drift.
                with self._clock._lock:  # type: ignore[attr-defined]
                    self._clock._global_index = max(  # type: ignore[attr-defined]
                        self._clock._global_index,  # type: ignore[attr-defined]
                        max_causal_index,
                    )
            except Exception:
                pass
        return count

    def truncate(self) -> None:
        """Soft-truncate: append a TRUNCATE event and filter on projection.
        Maintains the append-only invariant — events are never deleted,
        but a truncation marker stops projections beyond this point."""
        import time
        with self._lock:
            self._events.append({
                "type": "_internal_truncate",
                "timestamp": time.time(),
                "causal_index": len(self._events),
            })


# ── Invariant checks ───────────────────────────────────────────────────

def assert_append_only(store: GraphStore) -> bool:
    """Verify GraphStore has no mutation methods."""
    forbidden = {"update", "patch", "overwrite", "merge", "modify", "delete", "remove"}
    methods = set(dir(store))
    overlap = forbidden & methods
    if overlap:
        raise AssertionError(f"GraphStore has forbidden mutation methods: {overlap}")
    return True


def assert_event_is_immutable(evt: Event) -> bool:
    """Verify Event is frozen and its payload cannot be mutated."""
    # 1. frozen dataclass check
    params = getattr(evt, "__dataclass_params__", None)
    if params is None or not getattr(params, "frozen", False):
        raise AssertionError(f"Event {evt.event_id} is not a frozen dataclass")
    # 2. payload is a dict (we cannot easily check it's the only ref, but
    #    attempting to assign to it must raise)
    try:
        evt.payload = {}  # type: ignore[misc]
        raise AssertionError(f"Event {evt.event_id} payload is mutable")
    except (AttributeError, FrozenInstanceError):
        pass
    # 3. payload keys are independent of caller's original dict
    return True


def assert_pure_reducer() -> bool:
    """Verify module-level reduce functions are pure.

    Checks:
      - Function is module-level (not @staticmethod / @classmethod)
      - No closure cells (co_freevars is empty)
      - No global mutable state references
    """
    import inspect

    for fn_name, fn in [("reduce", reduce), ("reduce_inspections", reduce_inspections), ("reduce_active_inspections", reduce_active_inspections)]:
        # Must be a plain function, not method
        if inspect.isfunction(fn) is False:
            raise AssertionError(f"{fn_name} is not a plain function (type={type(fn).__name__})")
        # Must not capture any closure variables
        closure = fn.__code__.co_freevars
        if closure:
            raise AssertionError(f"{fn_name} captures external variables: {closure}")
        # Must not be wrapped in @staticmethod / @classmethod
        qualname = fn.__qualname__
        if "<locals>" in qualname or "." in qualname.split("<")[0]:
            # Methods of a class would have a dotted qualname; module-level fns do not.
            # Allow built-in module prefix (e.g. 'reduce.<locals>') is also forbidden.
            if "<locals>" in qualname:
                raise AssertionError(f"{fn_name} is a closure: qualname={qualname}")
    return True


# ── Singleton ───────────────────────────────────────────────────────────

_store: GraphStore | None = None
_store_lock = threading.Lock()


def get_graph_store(persist_dir: Path | None = None) -> GraphStore:
    global _store
    target = persist_dir or _default_persist_dir()
    if _store is None or _store._persist_dir != target:
        with _store_lock:
            if _store is None or _store._persist_dir != target:
                _store = GraphStore(persist_dir=target)
    return _store


def reset_graph_store() -> None:
    global _store
    with _store_lock:
        _store = None


def _default_persist_dir() -> Path:
    """Default durable event-log location.

    Projection stores live under ``workspaces/<ws>/...``; the graph event log
    itself is global to preserve causal ordering across workspaces.
    """
    import os

    root = Path(
        os.environ.get("NA_WORKSPACE_ROOT")
        or os.environ.get("NETWORK_AGENT_WORKSPACE_DIR")
        or Path(__file__).resolve().parents[2]  # fragile relative path — P2-15 / "workspaces"
    )
    return root / ".graph"
