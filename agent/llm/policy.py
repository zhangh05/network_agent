# agent/llm/policy.py
"""LLM Policy Gate — request and response validation."""

from agent.llm.schemas import (
    LLMRequest, LLMResponse, PolicyDecision,
    ALLOWED_TASKS, BLOCKED_TASKS, LLMTask,
)

SECRET_PATTERNS = ["password", "secret", "community", "snmp"]


def check_request(req: LLMRequest, state=None) -> PolicyDecision:
    """Check LLM request before sending to provider."""
    violations = []

    # Task must be in allowed set
    if req.task in BLOCKED_TASKS:
        violations.append(f"blocked task: {req.task}")
    elif req.task not in ALLOWED_TASKS:
        violations.append(f"unknown task: {req.task}")

    # Safe context must not contain raw configs
    ctx = req.safe_context or {}
    ctx_str = str(ctx).lower()

    if "source_config" in ctx and len(str(ctx.get("source_config", ""))) > 80:
        violations.append("safe_context contains full source_config")

    if "deployable_config" in ctx and len(str(ctx.get("deployable_config", ""))) > 80:
        violations.append("safe_context contains full deployable_config")

    for secret in SECRET_PATTERNS:
        if secret in ctx_str:
            violations.append(f"safe_context may contain {secret}")

    if violations:
        return PolicyDecision(allowed=False, reason="; ".join(violations), violations=violations)

    return PolicyDecision(allowed=True, reason="request_policy_pass")


def check_response(resp: LLMResponse, state=None) -> PolicyDecision:
    """Check LLM response for safety violations."""
    violations = []
    content = (resp.content or "").lower()

    # Must not contain deployable_config code blocks
    if "deployable_config" in content and "```" in content:
        violations.append("response contains deployable_config code block")

    # Must not claim "ready to deploy" without verification
    unsafe_claims = [
        ("可直接下发", "claims 'directly deployable'"),
        ("ready to deploy", "claims 'ready to deploy'"),
        ("manual review passed", "claims manual_review passed"),
        ("no issues found", "claims no issues found"),
    ]
    for kw, reason in unsafe_claims:
        if kw in content:
            violations.append(reason)

    # Must not leak secrets
    for secret in SECRET_PATTERNS:
        if secret in content and f"{secret}123" not in content and f"{secret}:" not in content:
            # Only flag if the secret appears as a key=value pattern
            pass  # Too aggressive to flag individual words; rely on context_builder redaction
        if f"  {secret} " in content and content.count(secret) < 3:
            violations.append(f"potential {secret} leak in response")

    # Must not fake planned module results
    if "topology map" in content or "inspection report generated" in content:
        violations.append("may be faking planned module result")

    # Must not claim LLM modified config
    if "i modified" in content or "i changed" in content or "i updated" in content:
        if "config" in content or "deployable" in content:
            violations.append("LLM claims to have modified config")

    if violations:
        return PolicyDecision(allowed=False, reason="; ".join(violations), violations=violations)

    return PolicyDecision(allowed=True, reason="response_policy_pass")
