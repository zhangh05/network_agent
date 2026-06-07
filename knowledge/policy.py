# knowledge/policy.py
"""Knowledge Index — security policy gates.

Determines what can be indexed, what content is safe for chunks,
and which chunks are LLM-safe.
"""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
WS_ROOT = ROOT / "workspaces"


# ═══════════════════ Index Eligibility ═══════════════════

INDEXABLE_TYPES = {
    "knowledge_doc", "report", "inspection_log",
    "input_config", "output_config", "topology_json",
    "topology_image", "export",
}

BLOCKED_LIFECYCLES = {"deleted", "quarantined"}


def can_index(artifact: dict) -> tuple[bool, str]:
    """Return (allowed, reason) for whether an artifact can be indexed."""
    a_type = artifact.get("artifact_type", "")
    lifecycle = artifact.get("lifecycle", "active")
    sensitivity = artifact.get("sensitivity", "internal")

    if lifecycle in BLOCKED_LIFECYCLES:
        return False, f"blocked_lifecycle:{lifecycle}"
    if a_type not in INDEXABLE_TYPES:
        return False, f"blocked_type:{a_type}"
    if sensitivity == "secret":
        return False, "blocked_sensitivity:secret"
    return True, "ok"


def can_generate_llm_chunks(sensitivity: str) -> bool:
    """Sensitive/confidential artifacts can have source metadata only,
    no LLM-safe chunks."""
    return sensitivity not in ("secret", "sensitive")


# ═══════════════════ Path Security ═══════════════════

def is_within_workspace(file_path: str, workspace_id: str) -> bool:
    """Check that a file path is within the workspace directory."""
    if not file_path:
        return False
    try:
        ws_path = (WS_ROOT / workspace_id).resolve()
        resolved = Path(file_path).resolve()
        resolved.relative_to(ws_path)
        return True
    except (ValueError, OSError):
        return False


def has_absolute_path(text: str, workspace_id: str) -> bool:
    """Detect if text contains absolute paths (e.g. /Users/...)."""
    # Look for unix-style absolute paths
    if re.search(r'(?:^|\s)/[a-zA-Z0-9_/.-]+', text):
        return True
    # Look for OS path separators
    if '\\' in text and re.search(r'[A-Z]:\\', text):
        return True
    return False


# ═══════════════════ Secret Detection ═══════════════════

SECRET_PATTERNS = [
    (re.compile(r'(password|passwd)\s*[:=]\s*\S+', re.I), "password"),
    (re.compile(r'(secret|secrets)\s*[:=]\s*\S+', re.I), "secret"),
    (re.compile(r'(token|api_key|apikey|key)\s*[:=]\s*\S{8,}', re.I), "token"),
    (re.compile(r'(community)\s+\S+', re.I), "community"),
    (re.compile(r'(private_key|ssh-key|sshkey)', re.I), "private_key"),
    (re.compile(r'(enable\s+secret)\s+\S+', re.I), "enable_secret"),
    (re.compile(r'(snmp-server\s+host)\s+\S+', re.I), "snmp"),
    (re.compile(r'(authentication-key|auth-key)\s+\S+', re.I), "auth_key"),
]


def detect_secrets(text: str) -> list[tuple[str, str]]:
    """Detect secret patterns in text. Returns [(pattern_type, matched_text), ...]."""
    found = []
    for pattern, ptype in SECRET_PATTERNS:
        for match in pattern.finditer(text):
            found.append((ptype, match.group()[:60]))
    return found


def contains_secret_pattern(text: str) -> bool:
    """Check if text contains any secret patterns."""
    return len(detect_secrets(text)) > 0


def redact_secrets(text: str) -> str:
    """Redact secret patterns from text."""
    for pattern, _ in SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    return text


# ═══════════════════ Content Safety ═══════════════════

def extract_safe_excerpt(text: str, max_chars: int = 200) -> str:
    """Extract a safe excerpt, redacting secrets and truncating."""
    safe = redact_secrets(text)
    # Remove excessively long lines
    lines = safe.split("\n")
    result_lines = []
    total = 0
    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            continue
        # Skip lines that look like config blocks
        if re.match(r'^\s*(interface|hostname|ip\s+address|router|switch|snmp)', line_stripped, re.I):
            continue
        line_len = len(line_stripped)
        if total + line_len > max_chars:
            remaining = max_chars - total
            if remaining > 20:
                result_lines.append(line_stripped[:remaining])
            break
        result_lines.append(line_stripped)
        total += line_len + 1

    result = "\n".join(result_lines)
    if len(result) < len(safe.rstrip()):
        result += "..."
    return result
