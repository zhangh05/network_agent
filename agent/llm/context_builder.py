# agent/llm/context_builder.py
"""Safe context builder — strips secrets, limits data to summary only."""

from agent.state import NetworkAgentState

MAX_SAMPLES = 5
SECRET_PATTERNS = ["password", "secret", "community", "snmp", "tacacs", "radius", "key_string"]


def build_safe_context(state: NetworkAgentState) -> dict:
    """Build a safe context dict for LLM consumption. No raw configs, no secrets."""

    result = state.tool_results or {}
    verification = state.verification or {}

    ctx = {
        "intent": state.intent,
        "active_module": state.active_module,
        "selected_skill": state.selected_skill,
        "translator_entry": result.get("translator_entry", "unknown"),
        "verification_status": verification.get("status", "unknown"),
    }

    if state.intent == "translate_config":
        mr = result.get("manual_review", [])
        us = result.get("unsupported", [])
        sn = result.get("semantic_near", [])

        ctx["deployable_line_count"] = len(result.get("deployable_config", "").split("\n"))
        ctx["manual_review_count"] = len(mr)
        ctx["semantic_near_count"] = len(sn)
        ctx["unsupported_count"] = len(us)

        # Limited samples only
        ctx["manual_review_samples"] = _redact_samples(mr[:MAX_SAMPLES])
        ctx["unsupported_samples"] = _redact_samples(us[:MAX_SAMPLES])

        # Audit summary (no raw config)
        audit = result.get("audit", {})
        ctx["audit_summary"] = audit.get("counts", {})

    # Memory hits summary
    ctx["memory_hits_summary"] = [h.get("title", "") for h in state.memory_hits[:3]]

    # Module status
    ctx["module_status"] = state.context.get("modules", {})
    ctx["planned_modules"] = [
        m for m, s in state.context.get("modules", {}).items() if s == "planned"
    ]

    return ctx


def _redact_samples(items: list) -> list:
    """Redact secrets from sample items."""
    cleaned = []
    for item in items:
        d = {}
        for k, v in item.items():
            if any(secret in str(k).lower() for secret in SECRET_PATTERNS):
                d[k] = "[REDACTED]"
            elif any(secret in str(v).lower() for secret in SECRET_PATTERNS):
                d[k] = "[REDACTED]"
            else:
                d[k] = v
        cleaned.append(d)
    return cleaned
