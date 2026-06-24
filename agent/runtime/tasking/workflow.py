# agent/runtime/tasking/workflow.py
"""Build and manage WorkflowPlan from a TaskPlan. v3.3: dynamic step ops."""

from __future__ import annotations

import uuid
from typing import Optional, List

from agent.runtime.tasking.models import TaskPlan, WorkflowPlan, StepPlan
from agent.runtime.state.models import RuntimeState


class WorkflowPlanner:
    """Convert a TaskPlan into a WorkflowPlan with StepPlan entries.

    v3.3: supports dynamic step insertion/removal/reordering for long tasks
    that discover new requirements mid-execution.
    """

    def build(
        self,
        task_plan: TaskPlan,
        ctx=None,
        state: Optional[RuntimeState] = None,
    ) -> WorkflowPlan:
        workflow_id = f"wf_{uuid.uuid4().hex[:12]}"
        steps = []
        for i, step_desc in enumerate(task_plan.steps):
            step = StepPlan(
                step_id=f"step_{uuid.uuid4().hex[:12]}",
                task_id=task_plan.task_id,
                title=step_desc[:80],
                goal=step_desc,
                order=i,
                completion_check=f"Step {i} done: {step_desc[:40]}",
            )
            steps.append(step)

        return WorkflowPlan(
            workflow_id=workflow_id,
            task_id=task_plan.task_id,
            steps=steps,
        )

    @staticmethod
    def insert_step(
        workflow: WorkflowPlan,
        title: str,
        goal: str,
        after_order: int = -1,
    ) -> Optional[StepPlan]:
        """Dynamically insert a step into the workflow.

        after_order=-1 means append at end.
        Returns the new StepPlan or None on failure.
        """
        new_step = StepPlan(
            step_id=f"step_{uuid.uuid4().hex[:12]}",
            task_id=workflow.task_id,
            title=title[:80],
            goal=goal,
            order=after_order + 1,
        )
        insert_at = min(len(workflow.steps), after_order + 1)
        workflow.steps.insert(insert_at, new_step)
        # Re-order all subsequent steps
        for i in range(insert_at, len(workflow.steps)):
            workflow.steps[i].order = i
        return new_step

    @staticmethod
    def remove_step(workflow: WorkflowPlan, step_id: str) -> bool:
        """Remove a step by ID. Returns True if removed."""
        for i, s in enumerate(workflow.steps):
            if s.step_id == step_id:
                workflow.steps.pop(i)
                for j in range(i, len(workflow.steps)):
                    workflow.steps[j].order = j
                return True
        return False

    def reorder_steps(
        self,
        workflow: WorkflowPlan,
        step_ids: List[str],
    ) -> bool:
        """Re-order steps to match the given step_id sequence.

        step_ids must contain all step IDs exactly once.
        Returns True on success.
        """
        existing_ids = {s.step_id for s in workflow.steps}
        if set(step_ids) != existing_ids:
            return False
        id_to_step = {s.step_id: s for s in workflow.steps}
        new_steps = []
        for i, sid in enumerate(step_ids):
            step = id_to_step[sid]
            step.order = i
            new_steps.append(step)
        workflow.steps = new_steps
        return True

    @staticmethod
    def plan_dynamic_step(
        workflow: WorkflowPlan,
        title: str,
        goal: str,
        depends_on: Optional[List[str]] = None,
    ) -> StepPlan:
        """Create a StepPlan without inserting it — for deferred insertion."""
        return StepPlan(
            step_id=f"step_{uuid.uuid4().hex[:12]}",
            task_id=workflow.task_id,
            title=title[:80],
            goal=goal,
            order=len(workflow.steps),
            required_evidence=[],
            required_actions=depends_on or [],
        )
