"""Memory redaction — strip secrets before persisting."""

import re

# Patterns are split into two groups:
# 1. KEYWORD patterns — keep the keyword (e.g. "password") but mask the value
# 2. FULL patterns — mask the entire match (e.g. "sk-abc123...")
_KEYWORD_PATTERNS = [
    r'(password)\s+\S+', r'(secret)\s+\S+', r'(community)\s+\S+',
    r'(key)\s+\S+', r'(pre-shared-key)\s+\S+', r'(tacacs.*key)\s+\S+',
    r'(radius.*key)\s+\S+', r'(api[_-]?key[=:]\s*)\S+',
    r'(authorization)\s+\S+', r'(token[=:]\s*)\S+',
    r'(OPENAI_API_KEY[=:]\s*)\S+', r'(DEEPSEEK_API_KEY[=:]\s*)\S+',
    r'(MINIMAX_API_KEY[=:]\s*)\S+', r'(ipsec)\s+\S+\s+\S+',
]

_FULL_MASK_PATTERNS = [
    r'sk-[A-Za-z0-9]{20,}',
    r'private[_-]?key',
]

MASK = "[REDACTED_SECRET]"

def redact_text(text: str) -> str:
    if not text: return text
    # Keyword patterns: keep the keyword, mask the secret value
    for pat in _KEYWORD_PATTERNS:
        text = re.sub(pat, lambda m: m.group(1) + " " + MASK, text, flags=re.IGNORECASE)
    # Full-mask patterns: replace entire match
    for pat in _FULL_MASK_PATTERNS:
        text = re.sub(pat, MASK, text, flags=re.IGNORECASE)
    return text

def redact_dict(data: dict) -> dict:
    if not data: return data
    result = {}
    for k, v in data.items():
        if any(s in str(k).lower() for s in ["password","secret","key","token","community"]):
            result[k] = MASK
        elif isinstance(v, dict):
            result[k] = redact_dict(v)
        elif isinstance(v, list):
            result[k] = [redact_dict(i) if isinstance(i,dict) else redact_text(str(i)) for i in v]
        elif isinstance(v, str):
            result[k] = redact_text(v)
        else:
            result[k] = v
    return result

def contains_secret(text: str) -> bool:
    if not text: return False
    for pat in _KEYWORD_PATTERNS + _FULL_MASK_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return True
    return False

def summarize_config_safely(config: str) -> dict:
    if not config: return {"line_count": 0, "has_secrets": False}
    lines = config.strip().split("\n")
    return {"line_count": len(lines), "has_secrets": contains_secret(config),
            "first_lines": [redact_text(l)[:80] for l in lines[:3]]}
