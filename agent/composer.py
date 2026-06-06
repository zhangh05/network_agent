# agent/composer.py
"""Response composer — builds final output from execution results."""

from agent.state import NetworkAgentState


def compose(state: NetworkAgentState) -> NetworkAgentState:
    """Build final_response from skill_results / tool_results and verification."""
    if state.error and not state.final_response:
        state.final_response = f"Error: {state.error}"
        state.done = True
        return state

    sr = state.skill_results or state.tool_results
    if not sr:
        state.final_response = "No result produced."
        state.done = True
        return state

    result = sr if isinstance(sr, dict) else (sr[-1] if isinstance(sr, list) and sr else {})

    if result.get("ok"):
        lines = []
        if result.get("deployable_config"):
            lines.append("Deployable config:")
            lines.append(f"```\n{result['deployable_config']}\n```")
        if result.get("manual_review"):
            lines.append(f"\nManual review items: {len(result['manual_review'])}")
        state.final_response = "\n".join(lines) or "Translate completed."
    else:
        state.final_response = f"Error: {result.get('error', 'unknown')}"

    state.done = True
    return state
