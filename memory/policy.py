"""Memory policy — enforce what can and can't be written."""

from memory.redaction import contains_secret, redact_text


class PolicyDecision:
    def __init__(self, allowed: bool = True, reason: str = ""):
        self.allowed = allowed
        self.reason = reason
        self.redaction_needed = False
        self.violations = []


def check_sensitive_content(content: str) -> PolicyDecision:
    """Check if content contains sensitive data that shouldn't be stored."""
    if not content:
        return PolicyDecision(allowed=True)

    p = PolicyDecision(allowed=True)

    # Detect full config dumps
    if "source_config" in content and len(content) > 500:
        p.violations.append("full_source_config")
    if "deployable_config" in content and len(content) > 500:
        p.violations.append("full_deployable_config")

    # Detect secrets
    if contains_secret(content):
        p.violations.append("contains_secret")
        p.redaction_needed = True

    # Block if any violation
    if p.violations:
        p.allowed = False
        p.reason = "; ".join(p.violations)

    return p


def can_write_memory(
    memory_type: str,
    content: str,
    confidence: str = "system_generated",
) -> PolicyDecision:
    """Check if a memory record can be written.
    
    Rules:
    - Never store full configs.
    - Secrets must be redacted (redaction_needed=True, not blocked).
    - long_term/decision/translation_rule require user_confirmed.
    - LLM-generated content defaults to short_term or run_summary.
    """
    # Block full configs (only for system-generated, not user-confirmed)
    if confidence != "user_confirmed":
        if "source_config" in content and len(content) > 500:
            return PolicyDecision(allowed=False, reason="full_source_config_blocked")
        if "deployable_config" in content and len(content) > 500:
            return PolicyDecision(allowed=False, reason="full_deployable_config_blocked")

    # Secrets — redact, don't block (after redaction content is safe)
    has_secret = contains_secret(content)
    decision = PolicyDecision(allowed=True)

    if has_secret:
        decision.redaction_needed = True

    # Long-term memory types require user confirmation
    long_term_types = ("decision", "translation_rule", "user_preference", "device_profile")
    if memory_type in long_term_types:
        if confidence != "user_confirmed":
            return PolicyDecision(
                allowed=False,
                reason=f"{memory_type} requires user_confirmed",
            )

    # Content size guard for run_summary/knowledge_note
    if memory_type in ("run_summary", "knowledge_note") and len(content) > 2000:
        decision.redaction_needed = True  # suggest truncation

    if has_secret and not decision.redaction_needed:
        decision.redaction_needed = True

    return decision


def can_write_run(record: dict) -> bool:
    """Check if a run record is safe to write.
    
    Rules:
    - No full source_config in run records.
    - No full deployable_config in run records.
    - No API keys/secrets in run records.
    """
    s = str(record)
    if "source_config" in s and len(s) > 1000:
        return False
    if "deployable_config" in s and len(s) > 1000:
        return False
    return not contains_secret(s)


def can_write_workspace_state(state: dict) -> bool:
    """Check if workspace state is safe to write.
    
    Rules:
    - No full source_config in state.
    - No full deployable_config in state.
    - No API keys/secrets in state.
    """
    s = str(state).lower()

    # Check for full configs in state
    for kw in ["source_config", "deployable_config"]:
        val = state.get(kw, "")
        if isinstance(val, str) and len(val) > 200:
            return False
        if isinstance(val, dict):
            text_val = str(val)
            if kw in text_val and len(text_val) > 500:
                return False

    return not contains_secret(str(state))
