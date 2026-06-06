# agent/graph.py
"""Minimal Agent orchestrator graph — no LangGraph yet, skeleton only."""

from agent.state import NetworkAgentState
from agent.router import route
from agent.planner import plan
from agent.executor import execute
from agent.verifier import verify
from agent.composer import compose


def run(user_input: str, intent: str = "") -> dict:
    """Full agent pipeline: route → plan → execute → verify → compose."""
    state = NetworkAgentState(user_input=user_input, intent=intent)

    # Route
    state = route(state)
    if state.done and state.error:
        return _to_result(state, ok=False)

    # Plan
    state = plan(state)

    # Execute
    state = execute(state)
    if state.error:
        return _to_result(state, ok=False)

    # Verify
    state = verify(state)

    # Compose
    state = compose(state)

    return _to_result(state, ok=True)


def _to_result(state: NetworkAgentState, ok: bool) -> dict:
    result = {
        "ok": ok,
        "intent": state.intent,
        "active_module": state.active_module,
        "plan": state.plan,
        "verification": state.verification,
        "final_response": state.final_response,
    }
    if state.error:
        result["error"] = state.error
    if state.tool_results:
        result["tool_result"] = state.tool_results[-1]
    return result
