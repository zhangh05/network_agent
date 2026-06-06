# agent/nodes/planner.py
"""Planner — generates execution steps. Plan is set by intent_router; here we only validate."""

from agent.state import NetworkAgentState


def plan(state: NetworkAgentState) -> NetworkAgentState:
    """Validate and refine plan."""
    if not state.plan:
        state.plan = ["report_unknown"]
    return state
