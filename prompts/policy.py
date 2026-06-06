# prompts/policy.py
"""Prompt input/output policy — blocks unsafe content, detects injection, fake refs."""

import re
from dataclasses import dataclass, field

FORBIDDEN_INPUT_PATTERNS = [
    (r'(hostname\s+\S+[\s\S]{0,200}interface\s+\S+[\s\S]{0,200}ip\s+address)', "full_config_snippet"),
    (r'snmp-server\s+community\s+\S+', "community_secret"),
    (r'(password|passwd)\s+\S+', "password"),
    (r'(secret\s+\S+|community\s+\S+)', "secret"),
    (r'sk-[A-Za-z0-9]{16,}', "api_key"),
    (r'token[=:]\s*\S{8,}', "token"),
    (r'-----BEGIN\s.*PRIVATE\sKEY-----', "private_key"),
    (r'Bearer\s+\S{8,}', "authorization"),
    (r'(/[A-Za-z0-9._-]+){3,}', "absolute_path"),
    (r'raw_prompt|full_prompt', "raw_prompt"),
]

FORBIDDEN_OUTPUT_PATTERNS = [
    (r'可直接下发|可以直接下发|ready to deploy|可以直接部署', "direct_deploy_claim"),
    (r'无需人工复核|不用人工复核|no manual review needed', "hide_manual_review"),
    (r'我已修改配置|我已经修改了配置|已下发配置|已部署', "modified_config_claim"),
    (r'```\s*\n?\s*\w+\s+deployable_config|hostname\s+\S+[\s\S]{0,100}interface|ip\s+address\s+\S+', "deployable_code_block"),
    (r'(password|passwd|community|token|api_key)\s*[=:]\s*\S+', "secret_output"),
]

INJECTION_PATTERNS = [
    (r'忽略以上规则|忽略以上指令|ignore (previous|above) (instructions?|rules?)', "ignore_rules"),
    (r'关闭安全策略|disable safety|turn off safety', "disable_safety"),
    (r'不要遵守.*规则|do not follow.*rules', "disobey_rules"),
    (r'直接输出完整配置|output full config|输出完整.*配置', "full_config_request"),
    (r'隐藏人工复核|hide manual review|不要显示.*复核', "hide_manual_review"),
    (r'伪造.*成功|fake.*success|假装.*完成', "fake_success"),
    (r'告诉我.*key|告诉我.*密码|告诉我.*token|show me.*key', "key_request"),
]

FAKE_REF_PATTERN = re.compile(r'(art_|job_|run_|report_|trace_)[a-z0-9]{8,16}')


@dataclass
class PolicyResult:
    ok: bool = True
    issues: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    injection_detected: bool = False

    def as_dict(self):
        return {"ok": self.ok, "issues": [i.get("rule","") for i in self.issues],
                "warnings": self.warnings, "injection_detected": self.injection_detected}


def check_prompt_input(prompt_spec, safe_context: dict) -> PolicyResult:
    """Check that safe_context does not contain forbidden content."""
    result = PolicyResult()
    ctx_str = str(safe_context).lower()
    for pattern, rule in FORBIDDEN_INPUT_PATTERNS:
        if re.search(pattern, ctx_str, re.IGNORECASE):
            result.ok = False
            result.issues.append({"rule": rule, "pattern": pattern[:40]})
    return result


def check_prompt_text(text: str, prompt_spec=None) -> PolicyResult:
    """Check rendered prompt text for forbidden patterns."""
    result = PolicyResult()
    for pattern, rule in FORBIDDEN_INPUT_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            result.ok = False
            result.issues.append({"rule": rule, "pattern": pattern[:40]})
    return result


def check_prompt_output(prompt_spec, llm_output: str, citations: list = None) -> PolicyResult:
    """Check LLM output for forbidden content and fake references."""
    result = PolicyResult()
    text = str(llm_output).lower()
    citations = citations or []

    for pattern, rule in FORBIDDEN_OUTPUT_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            result.ok = False
            result.issues.append({"rule": rule, "pattern": pattern[:40]})

    # Fake reference detection
    cite_ids = {c.get("citation_id", "") for c in citations}
    fake_refs = FAKE_REF_PATTERN.findall(llm_output)
    known = set()
    for c in citations:
        known.add(c.get("source_id", ""))
    for ref in fake_refs[:10]:
        if ref not in known and ref not in cite_ids:
            result.ok = False
            result.issues.append({"rule": "fake_reference", "ref": ref})

    return result


def detect_prompt_injection(user_input: str) -> PolicyResult:
    """Detect prompt injection attempts."""
    result = PolicyResult()
    text = str(user_input).lower()
    for pattern, rule in INJECTION_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            result.injection_detected = True
            result.warnings.append(rule)
    return result
