# agent/runtime/state/store.py
"""Persist RuntimeState into ctx.metadata['runtime_state']."""

from __future__ import annotations

import copy
from dataclasses import asdict
from typing import Optional

from agent.runtime.state.models import RuntimeState, SessionState, WorkspaceState

_KEY = "runtime_state"


class RuntimeStateStore:
    """Load / save RuntimeState from ctx.metadata."""

    def load(self, ctx) -> RuntimeState:
        raw = ctx.metadata.get(_KEY)
        if raw is None:
            return RuntimeState()
        if isinstance(raw, RuntimeState):
            return raw
        if isinstance(raw, dict):
            return self._from_dict(raw)
        return RuntimeState()

    def save(self, ctx, state: RuntimeState) -> None:
        ctx.metadata[_KEY] = asdict(state)

    # ------------------------------------------------------------------

    @staticmethod
    def _from_dict(d: dict) -> RuntimeState:
        from agent.runtime.state.models import (
            ArtifactState, ActionState, StepState,
            WorkflowState, TaskState,
        )
        session = SessionState(**d.get("session", {})) if d.get("session") else SessionState()
        workspace = WorkspaceState(**d.get("workspace", {})) if d.get("workspace") else WorkspaceState()

        tasks = [TaskState(**t) for t in d.get("tasks", [])]
        workflows = []
        for wf_raw in d.get("workflows", []):
            wf_copy = dict(wf_raw)
            steps_raw = wf_copy.pop("steps", [])
            steps = [StepState(**s) for s in steps_raw]
            workflows.append(WorkflowState(**wf_copy, steps=steps))
        artifacts = [ArtifactState(**a) for a in d.get("artifacts", [])]
        actions = [ActionState(**a) for a in d.get("actions", [])]

        active_task = TaskState(**d["active_task"]) if d.get("active_task") else None
        active_workflow = None
        if d.get("active_workflow"):
            aw = dict(d["active_workflow"])
            aw_steps = [StepState(**s) for s in aw.pop("steps", [])]
            active_workflow = WorkflowState(**aw, steps=aw_steps)

        return RuntimeState(
            session=session,
            workspace=workspace,
            active_task=active_task,
            active_workflow=active_workflow,
            tasks=tasks,
            workflows=workflows,
            artifacts=artifacts,
            actions=actions,
            metadata=d.get("metadata", {}),
        )
