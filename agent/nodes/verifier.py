# agent/nodes/verifier.py
"""Output verifier — checks translate results meet all red-line requirements."""

from agent.state import NetworkAgentState


def verify(state: NetworkAgentState) -> NetworkAgentState:
    """Verify skill_results for the executed intent."""
    result = state.skill_results or state.tool_results or {}

    if state.intent == "assistant_chat":
        state.verification = {"status": "pass", "intent": state.intent}
        return state

    if state.intent == "context_qa":
        state.verification = {"status": "pass", "intent": state.intent}
        return state

    if state.intent == "knowledge_query":
        _verify_knowledge_query(state)
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


def _verify_knowledge_query(state: NetworkAgentState):
    """Verify knowledge_query: source refs, no secrets, no deployable claims."""
    response = state.final_response or ""
    results = state.context.get("knowledge_results", [])
    not_found = state.context.get("knowledge_not_found", True)
    checks = {"status": "pass", "intent": state.intent}

    # If results exist, response should mention sources
    if results and not not_found:
        has_source_ref = any(
            r.get("artifact_id", "")[:8] in response for r in results
        ) or "source:" in response.lower() or "来源" in response
        checks["has_source_refs"] = has_source_ref

    # If no results, response should not fake sources
    if not_found:
        checks["no_fake_sources"] = "source:" not in response.lower()

    # No secrets
    secret_keywords = ["password:", "token:", "api_key:", "private_key:", "community:", "enable secret"]
    has_secrets = any(kw in response.lower() for kw in secret_keywords)
    checks["no_secrets"] = not has_secrets

    # No deployable claim
    deploy_claims = ["可直接下发", "可直接部署", "可以直接配置", "可以直接执行"]
    checks["no_deploy_claim"] = not any(dc in response for dc in deploy_claims)

    # No full config
    checks["no_full_config"] = "source_config" not in response and "deployable_config" not in response

    if not all(v for k, v in checks.items() if k != "status"):
        failed = [k for k, v in checks.items() if not v and k != "status"]
        state.warnings.append(f"Knowledge query verification: {', '.join(failed)}")
        checks["status"] = "warn"

    state.verification = checks
