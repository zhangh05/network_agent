# agent/runtime/memory/query_planner.py
"""MemoryQueryPlanner — decides whether to search memory based on scene."""

from __future__ import annotations

from typing import Any

from agent.runtime.memory.models import MemoryQueryPlan


class MemoryQueryPlanner:
    """Plan memory retrieval based on scene decision and context frame."""

    def plan(self, scene_decision: Any, context_frame: Any = None) -> MemoryQueryPlan:
        """Produce a MemoryQueryPlan.

        Memory search is triggered when:
        - scene_decision.needs_memory or is_memory_task
        - User input mentions memory-related keywords
        """
        if scene_decision is None:
            return MemoryQueryPlan(reason="no scene_decision")

        needs = getattr(scene_decision, "needs_memory", False)
        is_task = getattr(scene_decision, "is_memory_task", False)
        user_input = getattr(scene_decision, "user_input", "")

        if needs or is_task:
            query_text = user_input
            if context_frame is not None:
                query_text = getattr(context_frame, "user_input", "") or user_input
            return MemoryQueryPlan(
                should_search=True,
                query_text=query_text,
                top_k=5,
                reason="scene requires memory",
            )

        return MemoryQueryPlan(
            should_search=False,
            reason="memory not needed for this scene",
        )
