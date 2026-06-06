# agent/planner.py
"""Simple planner — generates execution steps based on intent."""

from agent.state import NetworkAgentState


def plan(state: NetworkAgentState) -> NetworkAgentState:
    """Generate a simple execution plan."""
    intent = state.intent

    if intent == "translate_config":
        state.plan = [
            "resolve_skill",
            "execute_translate",
            "verify_output",
            "compose_response",
        ]
    else:
        state.plan = ["report_planned"]

    return state
