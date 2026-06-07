# runtime/redaction.py
"""Runtime redaction — strips absolute paths and secrets from warning/error/audit strings.

Used by archive, retention, selfcheck, diagnostics, and API responses.
"""

import re

_SENSITIVE_PATTERNS = [
    (re.compile(r'(?:^|\s)/(?:Users|home|root|tmp|etc|var|opt|usr)/[^\s"\'<>]*'), '[PATH_REDACTED]'),
    (re.compile(r'(?:password|passwd|secret|community)\s+[^\s"\']+', re.IGNORECASE),
     lambda m: m.group(0).split()[0] + ' [REDACTED]'),
    (re.compile(r'(?:api_key|apikey|token)\s*[:=]\s*[^\s,}"\']+', re.IGNORECASE),
     lambda m: m.group(0).split('=')[0].split(':')[0] + '=[REDACTED]'),
    (re.compile(r'Bearer\s+[^\s"\'<>]+', re.IGNORECASE), 'Bearer [REDACTED]'),
    (re.compile(r'(sk-[a-zA-Z0-9]{4})[a-zA-Z0-9]+'), r'\1****[REDACTED]'),
]


def sanitize_output(text: str) -> str:
    """Remove absolute paths and secrets from a string."""
    for pattern, replacement in _SENSITIVE_PATTERNS:
        if callable(replacement):
            text = pattern.sub(replacement, text)
        else:
            text = pattern.sub(replacement, text)
    return text


def sanitize_dict(data: dict) -> dict:
    """Sanitize a dict — redact paths and secrets from all string values."""
    result = {}
    for key, value in data.items():
        if isinstance(value, str):
            result[key] = sanitize_output(value)
        elif isinstance(value, dict):
            result[key] = sanitize_dict(value)
        elif isinstance(value, list):
            result[key] = [sanitize_output(v) if isinstance(v, str) else v for v in value]
        else:
            result[key] = value
    return result
