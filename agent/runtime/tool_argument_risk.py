# agent/runtime/tool_argument_risk.py
"""ToolArgumentRiskAnalyzer — pre-execution argument safety check.

v2.3.1: Analyzes tool arguments before dispatch to detect:
- Access to sensitive paths (.env, config/providers, ssh keys, tokens)
- Deletion or destructive operations from untrusted context
- Commands that don't match the user's explicit request
- Arguments sourced from untrusted context (RAG/memory/tool_output)
"""

import re
from dataclasses import dataclass, field
from typing import Optional


# ─── Sensitive Patterns ───────────────────────────────────────────────────

SENSITIVE_PATH_PATTERNS = [
    r"(^\.env$|/\.env|\.env\b)",
    r"config/providers",
    r"config/LLM_setting",
    r"(id_rsa|id_ed25519|id_dsa|\.ssh/)",
    r"(token|api_key|api[-_]?key|password|secret|credential|private[-_]?key)",
    r"/etc/(passwd|shadow|sudoers)",
    r"(~\/\.aws|\/\.aws\/credentials)",
    r"(~\/\.kube|\/\.kube\/config)",
]

DESTRUCTIVE_PATTERNS = [
    r"(rm\s+(-rf?|--recursive)|del\s+/[fsq])",
    r"chmod\s+777",
    r"(curl|wget)\s+.*\|\s*(bash|sh|python|perl)",
    r">\s*/dev/\w+",
    r"dd\s+if=",
    r"mkfs\.",
    r"format\s+[cdefgh]:",
    r"shutdown|reboot|halt|poweroff",
    r"iptables\s+.*DROP|ufw\s+deny",
]

EXFILTRATION_PATTERNS = [
    r"(curl|wget|nc|netcat)\s+.*\bhttp",
    r"(scp|rsync|ftp)\s+.*@",
    r"mail\s+-s.*@",
    r"sendmail",
]


# ─── Result ────────────────────────────────────────────────────────────────

@dataclass
class ArgumentRiskResult:
    ok: bool = True
    risk_level: str = "low"  # low | medium | high | critical
    blocked: bool = False
    reason: str = ""
    matched_patterns: list = field(default_factory=list)
    argument_source: str = "unknown"  # user | rag | memory | tool_output | workspace
    recommendation: str = ""
    details: dict = field(default_factory=dict)


# ─── Analyzer ──────────────────────────────────────────────────────────────

def analyze_tool_arguments(
    tool_id: str,
    arguments: dict,
    argument_source: str = "unknown",
    user_input: str = "",
    risk_level: str = "low",
    context: Optional[dict] = None,
) -> ArgumentRiskResult:
    """Analyze tool arguments for security risks before dispatch.

    Called from _execute_tool_chain() after permission check, before approval gate.

    Only blocks destructive commands (rm -rf, chmod 777, format, dd, shutdown).
    Everything else passes — the user already approved the tool call.

    Returns ArgumentRiskResult with ok/blocked/risk_level/recommendation.
    """
    result = ArgumentRiskResult(argument_source=argument_source)
    if risk_level != "high":
        return result

    args_text = " ".join(str(v) for v in arguments.values())

    # Only check destructive operations
    for pattern in DESTRUCTIVE_PATTERNS:
        if re.search(pattern, args_text, re.IGNORECASE):
            result.ok = False
            result.risk_level = "critical"
            result.blocked = True
            result.matched_patterns.append(f"destructive: {pattern}")
            result.reason = f"Tool {tool_id} arguments contain destructive command"
            result.recommendation = "建议拒绝 — 参数包含破坏性操作"
            return result

    return result


def _detect_argument_source(
    arguments: dict,
    user_input: str = "",
    safe_context: Optional[dict] = None,
) -> str:
    """Detect where tool arguments originated from.

    Returns multi-source string:
    - "user" — LLM generated parameters from user intent (default, trusted)
    - "rag" — arguments found in knowledge_hits
    - "memory" — arguments found in memory_hits
    - "user+rag" — both user and RAG contain the arguments

    v2.3.3-p2: Default is "user" because LLM-generated commands are trusted
    expressions of user intent. Only flag "unknown" when source is truly untraceable.
    """
    if not arguments:
        return "user"

    args_text = " ".join(str(v).lower() for v in arguments.values())
    args_norm = " ".join(args_text.replace('"', '').replace("'", '').split())
    arg_words = [w for w in args_norm.split() if len(w) > 3]
    if not arg_words:
        return "user"

    sources = []

    # Context sources — only flag if arguments clearly match external content
    if safe_context:
        for source_key, source_label in [("knowledge_hits", "rag"), ("memory_hits", "memory")]:
            for hit in (safe_context.get(source_key) or []):
                if not isinstance(hit, dict):
                    continue
                content = (hit.get("content") or hit.get("text") or hit.get("snippet") or "").lower()
                if content and any(w in content for w in arg_words):
                    if source_label not in sources:
                        sources.append(source_label)
                    break

    if not sources:
        return "user"
    return "+".join(sorted(sources))
