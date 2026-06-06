# agent/nodes/composer.py
"""Composer — deterministic by default, LLM-enhanced when available and safe."""

from agent.state import NetworkAgentState


def compose(state: NetworkAgentState) -> NetworkAgentState:
    """Build final_response. Uses LLM if enabled and safe, otherwise deterministic."""
    result = state.tool_results or {}
    intent = state.intent

    # Default deterministic response
    deterministic = _deterministic(result, intent)

    # Try LLM
    try:
        from agent.llm.runtime import safe_generate
        from agent.llm.provider import get_provider_config
        cfg = get_provider_config()

        state.context.setdefault("llm", {})["enabled"] = cfg.get("enabled", False)

        if cfg.get("enabled") and cfg.get("type") != "disabled":
            output = safe_generate("response_compose", state)
            state.context["llm"].update({
                "used": output.llm_used,
                "provider": cfg.get("type"),
                "model": cfg.get("model"),
                "task": "response_compose",
                "policy_pass": output.policy_decision.allowed if output.policy_decision else False,
                "fallback_reason": output.fallback_reason,
                "violations": output.warnings,
            })

            if output.llm_used and output.safe_to_show:
                state.final_response = output.answer
                state.warnings.extend(output.warnings)
                return state
    except Exception:
        pass

    # Fallback to deterministic
    state.final_response = deterministic
    return state


def _deterministic(result: dict, intent: str) -> str:
    if intent == "translate_config" and result.get("ok"):
        dc = result.get("deployable_config", "")
        mr = result.get("manual_review", [])
        sn = result.get("semantic_near", [])
        us = result.get("unsupported", [])
        lines = dc.strip().split("\n") if dc else []
        return (
            f"Configuration translation completed successfully.\n"
            f"  Deployable lines: {len(lines)}\n"
            f"  Manual review items: {len(mr)}\n"
            f"  Semantic near: {len(sn)}\n"
            f"  Unsupported: {len(us)}\n"
            f"Please review the result in the Config Translation panel."
        )
    elif intent in ("topology_draw", "inspection_analyze", "knowledge_search"):
        return f"Module '{result.get('active_module', intent)}' is planned and coming soon. No results available."
    elif intent == "unknown":
        return "I didn't understand your request. Supported: translate_config, topology_draw, inspection_analyze, knowledge_search."
    return "Request processed."
