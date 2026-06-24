# agent/runtime/tasking/planner.py
"""Create a TaskPlan from a TaskSignal and user input."""

from __future__ import annotations

import uuid
from typing import Optional

from agent.runtime.tasking.models import TaskSignal, TaskPlan
from agent.runtime.state.models import RuntimeState


class TaskPlanner:
    """Produce a TaskPlan for new_task signals."""

    def plan(
        self,
        signal: TaskSignal,
        user_input: str,
        ctx=None,
        state: Optional[RuntimeState] = None,
    ) -> Optional[TaskPlan]:
        if signal.kind == "cancel_task":
            return TaskPlan(
                task_id=signal.referenced_task_id or "",
                title="Task Cancelled",
                steps=[],
                metadata={"cancelled": True},
            )
        if signal.kind != "new_task":
            return None

        task_id = f"task_{uuid.uuid4().hex[:12]}"
        title = user_input[:60].strip()
        # Extract rough steps from the input
        steps = self._extract_steps(user_input)

        return TaskPlan(
            task_id=task_id,
            title=title,
            user_goal=user_input,
            steps=steps,
            completion_criteria=f"All steps completed for: {title}",
        )

    @staticmethod
    def _extract_steps(text: str) -> list:
        """Best-effort step extraction from user text."""
        # Look for numbered steps or clause separators
        import re
        # Try numbered steps
        numbered = re.findall(r"(?:^|\n)\s*\d+[.、)]\s*(.+)", text)
        if numbered:
            return numbered

        # Try splitting by common connectors
        parts = re.split(r"[，,；;。\n]+", text)
        steps = [p.strip() for p in parts if len(p.strip()) > 4]
        if len(steps) >= 2:
            return steps

        return [text.strip()]
