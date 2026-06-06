# agent/nodes/skill_executor.py
"""Skill executor — routes to skill adapter, records tool_call."""

from agent.state import NetworkAgentState


def execute(state: NetworkAgentState) -> NetworkAgentState:
    """Execute the selected skill via its adapter."""
    skill = state.selected_skill
    if not skill:
        state.error = "No skill selected"
        return state

    # Record tool call attempt
    call = {
        "skill": skill,
        "module": state.active_module,
        "entrypoint": "python_adapter",
        "status": "failed",
    }

    if skill == "config_translation" and state.intent == "translate_config":
        try:
            from skills.config_translation.adapter import translate
            result = translate(
                source_config=state.payload.get("source_config", state.user_input),
                source_vendor=state.payload.get("source_vendor", "auto"),
                target_vendor=state.payload.get("target_vendor", "huawei"),
            )
            state.tool_results = result
            call["status"] = "success" if result.get("ok") else "failed"
            if not result.get("ok"):
                state.error = result.get("error", "translate failed")
        except Exception as exc:
            call["status"] = "failed"
            state.error = str(exc)
    else:
        state.tool_results = {"ok": False, "error": f"Skill '{skill}' not implemented"}
        call["status"] = "planned"
        state.warnings.append(f"Skill '{skill}' is planned (coming_soon)")

    state.tool_calls.append(call)
    return state
