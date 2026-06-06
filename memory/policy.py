"""Memory policy — enforce what can and can't be written."""

from memory.redaction import contains_secret, redact_text

class PolicyDecision:
    def __init__(self, allowed=True, reason=""):
        self.allowed = allowed
        self.reason = reason
        self.redaction_needed = False
        self.violations = []

def check_sensitive_content(content: str) -> PolicyDecision:
    if not content: return PolicyDecision(allowed=True)
    p = PolicyDecision(allowed=True)
    if "source_config" in content and len(content) > 500:
        p.violations.append("full_source_config")
    if "deployable_config" in content and len(content) > 500:
        p.violations.append("full_deployable_config")
    if contains_secret(content):
        p.violations.append("contains_secret")
        p.redaction_needed = True
    if p.violations:
        p.allowed = False
        p.reason = "; ".join(p.violations)
    return p

def can_write_memory(memory_type: str, content: str, confidence: str = "system_generated") -> PolicyDecision:
    if contains_secret(content):
        return PolicyDecision(allowed=False, reason="contains_secret")
    if memory_type in ("run_summary", "knowledge_note") and len(content) > 2000:
        return PolicyDecision(allowed=True, reason="ok", redaction_needed=True)
    if memory_type in ("decision", "translation_rule") and confidence != "user_confirmed":
        return PolicyDecision(allowed=False, reason="long_term requires user_confirmed")
    return PolicyDecision(allowed=True)

def can_write_workspace_state(state: dict) -> bool:
    s = str(state).lower()
    for kw in ["source_config", "deployable_config"]:
        if kw in s and len(str(state.get(kw, ""))) > 200:
            return False
    return not contains_secret(str(state))
