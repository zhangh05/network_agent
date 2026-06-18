# runtime/redaction.py
"""Runtime redaction — strips absolute paths and secrets from data structures.

Provides key-level and value-level redaction for dicts, lists, and strings.
Used by archive, retention, selfcheck, diagnostics, audit records, and API responses.

Functions:
  redact_text(text)           — redact a single string
  redact_value(value)         — redact any Python value (str/dict/list/other)
  redact_dict(data)           — deep-redact a dict (key-level + value-level)
  sanitize_runtime_output(data) — top-level entry for runtime output
"""

import re
import copy

# ── Sensitive key names (case-insensitive) ──
_SENSITIVE_KEYS = {
    "password", "passwd", "secret", "token", "api_key", "apikey",
    "key", "community", "authorization", "bearer", "private_key",
    "ssh_key", "psk", "pre_shared_key", "access_key", "secret_key",
}

# ── Value-level patterns ──
_VALUE_PATTERNS = [
    # Bearer tokens (before general authorization pattern)
    (re.compile(r'Bearer\s+[^\s"\'<>]+', re.IGNORECASE), 'Bearer [REDACTED]'),
    # OpenAI-style keys (before general key pattern)
    (re.compile(r'(sk-[a-zA-Z0-9]{4})[a-zA-Z0-9]+'), r'\1****[REDACTED]'),
    # Absolute paths (Unix + Windows)
    (re.compile(r'(?:^|\s|["\'])/(?:Users|home|root|tmp|etc|var|opt|usr)/[^\s"\'<>]*'),
     '[PATH_REDACTED]'),
    (re.compile(r'[A-Za-z]:\\[^\s"\'<>]+'), '[PATH_REDACTED]'),
    # Key-value secrets
    (re.compile(r'(?:password|passwd|secret|community)\s+[^\s"\']+', re.IGNORECASE),
     lambda m: re.split(r'\s+', m.group(0))[0] + ' [REDACTED]'),
    (re.compile(r'(?:api_key|apikey|token)\s*[:=]\s*[^\s,}"\']+', re.IGNORECASE),
     lambda m: re.split(r'[=:]', m.group(0), 1)[0] + '=[REDACTED]'),
    # Authorization headers (after Bearer)
    (re.compile(r'authorization\s*[:=]\s*[^\s,}"\']+', re.IGNORECASE), 'Authorization=[REDACTED]'),
]


def redact_text(text: str) -> str:
    """Apply value-level pattern redaction to a single string."""
    for pattern, replacement in _VALUE_PATTERNS:
        if callable(replacement):
            text = pattern.sub(replacement, text)
        else:
            text = pattern.sub(replacement, text)
    return text


def redact_value(value):
    """Redact any Python value — str, dict, list, or other."""
    if isinstance(value, str):
        return redact_text(value)
    elif isinstance(value, dict):
        return redact_dict(value)
    elif isinstance(value, list):
        return [redact_value(v) for v in value]
    return value


def redact_dict(data: dict) -> dict:
    """Deep-redact a dict with key-level and value-level redaction.

    Key-level: if key matches a sensitive key name, the value is replaced
    with '[REDACTED]' regardless of content.
    Value-level: string values are scanned for path/secret patterns.
    """
    result = {}
    for key, value in data.items():
        # Key-level check
        if key.lower() in _SENSITIVE_KEYS or any(
            sk in key.lower() for sk in _SENSITIVE_KEYS
        ):
            result[key] = "[REDACTED]"
        elif isinstance(value, dict):
            result[key] = redact_dict(value)
        elif isinstance(value, list):
            result[key] = [redact_value(v) for v in value]
        elif isinstance(value, str):
            result[key] = redact_text(value)
        else:
            result[key] = value
    return result


def sanitize_runtime_output(data) -> dict:
    """Top-level entry for sanitizing runtime output.

    Returns a deep copy — never mutates the original.
    Always produces JSON-serializable output.
    """
    return redact_dict(copy.deepcopy(data)) if isinstance(data, dict) else data


# ── Retired aliases for backward compatibility ──
sanitize_output = redact_text
sanitize_dict = redact_dict
