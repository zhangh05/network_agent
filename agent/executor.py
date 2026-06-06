# agent/executor.py
"""Skill executor — calls skill adapters to interact with modules."""

from agent.state import NetworkAgentState
from skills.config_translation.adapter import translate


def execute(state: NetworkAgentState) -> NetworkAgentState:
    """Execute the current intent via its skill adapter."""
    intent = state.intent

    if intent == "translate_config":
        # Delegate entirely to the skill adapter
        result = translate(
            source_config=state.user_input or "",
            source_vendor="auto",
            target_vendor="huawei",
        )
        state.skill_results = result
        state.tool_results.append(result)  # legacy: old code treated results as list

        if result.get("ok"):
            state.final_response = "Translate completed."
        else:
            state.error = result.get("error", "translate_config failed")
    else:
        state.error = f"No executor for intent: {intent}"

    return state
