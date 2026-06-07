# agent/nodes/verifier.py
"""Output verifier — checks translate results meet all red-line requirements."""

from agent.state import NetworkAgentState


def verify(state: NetworkAgentState) -> NetworkAgentState:
    """Verify skill_results for the executed intent."""
    result = state.skill_results or state.tool_results or {}

    if state.intent == "assistant_chat":
        state.verification = {"status": "pass", "intent": state.intent}
        return state

    if state.intent != "translate_config":
        state.verification = {"status": "planned", "intent": state.intent}
        return state

    checks = {}

    # Structural
    checks["has_deployable_config"] = "deployable_config" in result
    checks["has_manual_review"] = "manual_review" in result
    checks["has_semantic_near"] = "semantic_near" in result
    checks["has_unsupported"] = "unsupported" in result
    checks["has_audit"] = "audit" in result

    # Red-line
    checks["translator_entry_correct"] = result.get("translator_entry") == "translate_bundle"
    checks["no_full_output"] = "full_output" not in result
    checks["external_dep_clean"] = result.get("external_translator_dependency") in (False, None)
    checks["no_llm_deployable"] = result.get("translator_entry") == "translate_bundle"

    if result.get("ok"):
        checks["status"] = "pass" if all(checks.values()) else "fail"
        if not all(checks.values()):
            failed = [k for k, v in checks.items() if not v and k != "status"]
            state.warnings.append(f"Verification warnings: {', '.join(failed)}")
    else:
        checks["status"] = "fail"
        state.warnings.append("translate_config returned ok=False")

    state.verification = checks
    return state
