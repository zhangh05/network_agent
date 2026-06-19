# agent/runtime/tasking/workflow.py
"""Build a WorkflowPlan from a TaskPlan."""

from __future__ import annotations

import uuid
from typing import Optional

from agent.runtime.tasking.models import TaskPlan, WorkflowPlan, StepPlan
from agent.runtime.state.models import RuntimeState


class WorkflowPlanner:
    """Convert a TaskPlan into a WorkflowPlan with StepPlan entries."""

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
