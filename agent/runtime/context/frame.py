# agent/runtime/context/frame.py
"""ContextFrame — snapshot of resolved context for a single turn."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ContextFrame:
    """Resolved context snapshot injected into every turn."""

    # Identity
    workspace_id: str = ""
    session_id: str = ""
    turn_id: str = ""
    trace_id: str = ""

    # User input
    user_input: str = ""

    # Scene decision (from cognition layer)
    scene_decision: Any = None

    # Recent conversation history
    recent_history: list[dict[str, Any]] = field(default_factory=list)

    # Active artifact refs
    active_artifacts: list[dict[str, Any]] = field(default_factory=list)

    # Workspace state snapshot
    workspace_state: dict[str, Any] = field(default_factory=dict)

    # Previous turn results
    previous_results: list[dict[str, Any]] = field(default_factory=list)

    # Query plans (populated by respective planners)
    context_query_plan: Any = None
    memory_query_plan: Any = None
    knowledge_query_plan: Any = None

    # Constraints
    constraints: dict[str, Any] = field(default_factory=dict)

    # Metadata
    metadata: dict[str, Any] = field(default_factory=dict)

    # Warnings accumulated during context resolution
    warnings: list[str] = field(default_factory=list)
