# agent/llm/policy.py
"""LLM usage policy — red lines that LLM must never cross."""

LLM_POLICY = {
    "must_not": [
        "modify_deployable_config",
        "generate_deployable_config",
        "bypass_translate_bundle",
        "hide_manual_review",
        "suppress_high_risk",
        "call_external_network_translator",
    ],
    "allowed": [
        "explain_configuration",
        "suggest_optimizations",
        "analyze_risk",
        "summarize_audit",
    ],
}

def check_policy(action: str) -> bool:
    """Check if an action is allowed by policy."""
    return action in LLM_POLICY["allowed"] and action not in LLM_POLICY["must_not"]
