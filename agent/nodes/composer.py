# agent/nodes/composer.py
"""Deterministic composer — builds final_response without LLM."""

from agent.state import NetworkAgentState


def compose(state: NetworkAgentState) -> NetworkAgentState:
    """Build final_response."""
    if state.error:
        state.final_response = f"Agent error: {state.error}"
        return state

    result = state.tool_results or {}
    intent = state.intent

    if intent == "translate_config" and result.get("ok"):
        dc = result.get("deployable_config", "")
        mr = result.get("manual_review", [])
        sn = result.get("semantic_near", [])
        us = result.get("unsupported", [])
        lines = dc.strip().split("\n") if dc else []

        parts = [
            "Configuration translation completed successfully.",
            f"  Deployable lines: {len(lines)}",
            f"  Manual review items: {len(mr)}",
            f"  Semantic near: {len(sn)}",
            f"  Unsupported: {len(us)}",
            "Please review the result in the Config Translation panel.",
        ]
        state.final_response = "\n".join(parts)

    elif intent == "translate_config":
        state.final_response = f"Translation failed: {result.get('error', 'unknown')}"

    elif intent in ("topology_draw", "inspection_analyze", "knowledge_search"):
        state.final_response = f"Module '{state.active_module}' is planned and coming soon. No results available."

    elif intent == "unknown":
        state.final_response = (
            "I didn't understand your request. Supported intents:\n"
            "  - translate_config (configuration translation)\n"
            "  - topology_draw, inspection_analyze, knowledge_search (planned)"
        )
    else:
        state.final_response = "Request processed." if result else "No results."

    return state
