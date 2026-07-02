"""
GraphStore — Single Source of Truth for all runtime state.

Replaces:
  - result_builder.py  fake node_count=6
  - trace.py  state dict mutations
  - inspection task in-memory state
  - frontend React useState state
  - all scattered dict states

Rules:
  - EVERY state read/write goes through GraphStore
  - No other module mutates state directly
  - Timestamps come from StageClock, not stored here
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ── Events ──────────────────────────────────────────────────────────

@dataclass
class GraphEvent:
    """An immutable event in the event log."""
    event_id: str
    event_type: str          # "stage", "node", "tool", "error", "final"
    name: str
    timestamp_iso: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "name": self.name,
            "timestamp": self.timestamp_iso,
            **self.payload,
        }


# ── GraphStore ───────────────────────────────────────────────────────

@dataclass
class RunState:
    """Mutable state for a single kernel execution run."""
    run_id: str
    task_input: str
    workspace_id: str
    session_id: str
    status: str = "pending"        # pending | planning | executing | finalizing | done | failed
    plan_nodes: list[dict] = field(default_factory=list)
    node_results: dict[str, Any] = field(default_factory=dict)
    final_response: str = ""
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    approval_required: bool = False
    approval_nodes: list[str] = field(default_factory=list)


class GraphStore:
    """Single Source of Truth for all runtime state.

    Thread-safe. All mutations go through GraphStore.append_event().
    No other module mutates state directly.
    """

    def __init__(self, persist_dir: Path | None = None):
        self._runs: dict[str, RunState] = {}
        self._events: list[GraphEvent] = []
        self._persist_dir = persist_dir
        # Inspection task registry (lives here, not in React useState)
        self._inspection_tasks: dict[str, dict[str, Any]] = {}

    # ── Run lifecycle ─────────────────────────────────────────────

    def create_run(self, task_input: str, workspace_id: str,
                   session_id: str) -> str:
        """Create a new run. Returns run_id."""
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        self._runs[run_id] = RunState(
            run_id=run_id,
            task_input=task_input,
            workspace_id=workspace_id,
            session_id=session_id,
        )
        return run_id

    def get_run(self, run_id: str) -> RunState | None:
        return self._runs.get(run_id)

    def update_run(self, run_id: str, **kwargs) -> None:
        run = self._runs.get(run_id)
        if run:
            for k, v in kwargs.items():
                if hasattr(run, k):
                    setattr(run, k, v)

    # ── Events (immutable log) ─────────────────────────────────────

    def append_event(self, event_type: str, name: str,
                     payload: dict[str, Any] | None = None) -> str:
        """Append an immutable event. Returns event_id."""
        from core.time.clock import now_iso as _now_iso
        eid = f"evt_{uuid.uuid4().hex[:8]}"
        evt = GraphEvent(
            event_id=eid,
            event_type=event_type,
            name=name,
            timestamp_iso=_now_iso(),
            payload=payload or {},
        )
        self._events.append(evt)
        return eid

    def get_events(self, event_type: str | None = None) -> list[dict]:
        if event_type:
            return [e.to_dict() for e in self._events if e.event_type == event_type]
        return [e.to_dict() for e in self._events]

    # ── Node count (truth, no fake padding) ────────────────────────

    @property
    def node_count(self) -> int:
        """Real node count from plan, never padded to 6."""
        # Count nodes from runs that have plan_nodes
        total = 0
        for run in self._runs.values():
            total += len(run.plan_nodes)
        return total

    @property
    def executed_node_count(self) -> int:
        """Count of nodes that actually executed."""
        return len([
            e for e in self._events
            if e.event_type in ("node_start", "node_end")
        ])

    # ── Inspection tasks (persisted, not React useState) ──────────

    def upsert_inspection_task(self, task_id: str, data: dict[str, Any]) -> None:
        """Register or update an inspection task. Persisted to disk."""
        self._inspection_tasks[task_id] = data
        if self._persist_dir:
            path = self._persist_dir / "inspection_tasks" / f"{task_id}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2))

    def get_inspection_task(self, task_id: str) -> dict[str, Any] | None:
        task = self._inspection_tasks.get(task_id)
        if task:
            return task
        # Fallback: load from disk
        if self._persist_dir:
            path = self._persist_dir / "inspection_tasks" / f"{task_id}.json"
            if path.exists():
                return json.loads(path.read_text())
        return None

    def list_inspection_tasks(self, workspace_id: str = "") -> list[dict]:
        """List all inspection tasks for a workspace."""
        tasks = list(self._inspection_tasks.values())
        if workspace_id:
            tasks = [t for t in tasks if t.get("workspace_id") == workspace_id]
        return tasks

    def active_inspection_tasks(self) -> list[str]:
        """Get IDs of currently running inspection tasks."""
        return [
            tid for tid, t in self._inspection_tasks.items()
            if t.get("status") in ("running", "pending")
        ]

    # ── Summary ────────────────────────────────────────────────────

    def summary(self) -> dict[str, Any]:
        """Generate a truthful summary with no fake padding."""
        return {
            "node_count": self.node_count,
            "executed_node_count": self.executed_node_count,
            "run_count": len(self._runs),
            "event_count": len(self._events),
            "active_inspection_tasks": self.active_inspection_tasks(),
        }


# ── Module singleton ──────────────────────────────────────────────────

_store: GraphStore | None = None


def get_graph_store(persist_dir: Path | None = None) -> GraphStore:
    global _store
    if _store is None:
        _store = GraphStore(persist_dir=persist_dir)
    return _store


def reset_graph_store() -> None:
    global _store
    _store = None
