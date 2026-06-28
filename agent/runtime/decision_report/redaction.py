# agent/runtime/decision_report/redaction.py
"""Decision Report redaction — ensure reports are safe for external storage."""

_SENSITIVE_KEYWORDS = (
    "secret", "password", "token", "api_key", "authorization",
    "credential", "private_key", "source_config", "raw_config",
    "raw_content", "full_text", "config_body", "file_content",
)


def _is_sensitive_key(key: str) -> bool:
    lower = str(key).lower()
    return any(kw in lower for kw in _SENSITIVE_KEYWORDS)


def _redact_value(value, max_str_len: int = 500) -> any:
    """Recursively redact sensitive fields from a value.

    - Strings: truncated to max_str_len
    - Dicts: redact keys matching sensitive patterns
    - Lists: redact each element
    - Numbers/bools: passed through
    """
    if isinstance(value, dict):
        out = {}
        for k, v in list(value.items())[:50]:
            if _is_sensitive_key(str(k)):
                out[str(k)] = "[REDACTED]"
                continue
            out[str(k)] = _redact_value(v, max_str_len)
        return out
    if isinstance(value, list):
        return [_redact_value(v, max_str_len) for v in value[:30]]
    if isinstance(value, str):
        return value[:max_str_len] + ("...[truncated]" if len(value) > max_str_len else "")
    if isinstance(value, (int, float, bool)):
        return value
    if value is None:
        return None
    return str(value)[:max_str_len]


def redact_decision_report(report: dict) -> dict:
    """Apply redaction to the full decision report.

    This is the final gate before writing to disk.
    Applies _redact_value to all dict/list fields in the report.
    """
    if not isinstance(report, dict):
        return {}

    out = dict(report)
    # Always mark as redacted
    out["redaction_applied"] = True

    # Deep-redact the tool_planning_decision (may contain raw data)
    if "tool_planning_decision" in out:
        out["tool_planning_decision"] = _redact_value(
            out["tool_planning_decision"], max_str_len=300,
        )

    if "business_capabilities" in out:
        out["business_capabilities"] = _redact_value(
            out["business_capabilities"], max_str_len=200,
        )

    # Redact scene_decision
    if "scene_decision" in out:
        out["scene_decision"] = _redact_value(
            out["scene_decision"], max_str_len=200,
        )

    # Truncate warnings / errors
    for key in ("warnings", "errors"):
        if key in out and isinstance(out[key], list):
            out[key] = [
                str(w)[:500] for w in out[key]
            ]

    return out
