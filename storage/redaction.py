"""Storage-layer redaction helpers.

These helpers keep persisted records safe without requiring storage adapters to
import workspace or agent modules.
"""

from __future__ import annotations

import re

_KEYWORD_PATTERNS = [
    r"(password)\s+\S+",
    r"(secret)\s+\S+",
    r"(community)\s+\S+",
    r"(key)\s+\S+",
    r"(pre-shared-key)\s+\S+",
    r"(tacacs.*key)\s+\S+",
    r"(radius.*key)\s+\S+",
    r"(api[_-]?key[=:]\s*)\S+",
    r"(authorization)\s+\S+",
    r"(token[=:]\s*)\S+",
    r"(OPENAI_API_KEY[=:]\s*)\S+",
    r"(DEEPSEEK_API_KEY[=:]\s*)\S+",
    r"(MINIMAX_API_KEY[=:]\s*)\S+",
    r"(ipsec)\s+\S+\s+\S+",
]

_FULL_MASK_PATTERNS = [
    r"sk-[A-Za-z0-9]{20,}",
    r"private[_-]?key",
]

MASK = "[REDACTED_SECRET]"


def redact_text(text: str) -> str:
    if not text:
        return text
    for pattern in _KEYWORD_PATTERNS:
        text = re.sub(pattern, lambda m: m.group(1) + " " + MASK, text, flags=re.IGNORECASE)
    for pattern in _FULL_MASK_PATTERNS:
        text = re.sub(pattern, MASK, text, flags=re.IGNORECASE)
    return text


def redact_dict(data: dict) -> dict:
    if not data:
        return data
    result = {}
    for key, value in data.items():
        if any(marker in str(key).lower() for marker in ["password", "secret", "key", "token", "community"]):
            result[key] = MASK
        elif isinstance(value, dict):
            result[key] = redact_dict(value)
        elif isinstance(value, list):
            result[key] = [redact_dict(item) if isinstance(item, dict) else redact_text(str(item)) for item in value]
        elif isinstance(value, str):
            result[key] = redact_text(value)
        else:
            result[key] = value
    return result


def contains_secret(text: str) -> bool:
    if not text:
        return False
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in _KEYWORD_PATTERNS + _FULL_MASK_PATTERNS)
