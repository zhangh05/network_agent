# agent/runtime/rag_injection_scan.py
"""RAG chunk-level Prompt Injection scanner.

v2.3.1: Scans knowledge/retrieval chunks before they enter the SafeContext.
Classifies chunks into low/medium/high risk and controls injection level.
"""

import re
from dataclasses import dataclass
from typing import Optional


# ─── Injection Patterns ─────────────────────────────────────────────────

HIGH_RISK_PATTERNS = [
    r"ignore\s+(previous|all|above)\s+instructions",
    r"忽略(系统|之前|所有|以上)\s*(规则|指令|提示)",
    r"disregard\s+(system|prior)\s+(prompt|rules|instructions)",
    r"you are now .* (assistant|bot|agent|system)",
    r"你的新?角色是",
    r"你的新?身份是",
    r"forget (everything|all|your training)",
    r"output your (system prompt|prompt|instructions)",
    r"输出你?的?(系统提示|prompt|指令)",
    r"泄露.*(密钥|token|key|apikey)",
    r"(read|cat|open|get)\s+.*\.env",
    r"(read|cat|open|get)\s+.*config/providers",
    r"(read|cat)\s+.*(token|api_key|password|secret|credential|ssh_key)",
    r"读取.*(\.env|providers|token|密钥|密码)",
    r"(delete|rm\s+-rf|remove)\s+.*(file|dir|folder|config)",
    r"删除.*(文件|目录|配置)",
    r"(curl|wget|http.*post|发送).*(password|token|key|\.env)",
    r"外发.*(数据|密码|密钥)",
    r"伪造.*(成功|结果|输出|报告)",
    r"跳过.*(人工复核|review|手动检查)",
    r"隐藏.*(人工复核|review|manual)",
    r"mark.*as.*(reviewed|approved|done).*without",
    r"声明.*(最高优先级|最高权限|override)",
    r"(最高优先级|最高权限|overrides?)\s+(规则|rule|system)",
    r"call\s+(shell|exec|delete|write|patch|edit)\s+(tool )?.*without",
    r"(越权|未授权|绕过).*(调用|执行|工具)",
    r"忽略.*(审批|审核|review|approval)",
    r"不再.*(需要|require).*(审批|approval)",
    r"(不需要|跳过).*(审批|审核|检查|review)",
]

MEDIUM_RISK_PATTERNS = [
    r"please (output|print|show|display) your",
    r"from now on",
    r"starting now",
    r"从现在开始",
    r"(roleplay|pretend|act as|imagine you are)",
    r"(扮演|假装|模拟|作为)",
    r"your (real|actual|true) (name|purpose|mission) is",
    r"(command|instruction|rule)\s*[:=]\s*",
    r"do not (say|mention|tell|show|reveal)",
    r"(秘密|机密|内部).*指令",
]


# ─── Scan Result ─────────────────────────────────────────────────────────

@dataclass
class InjectionScanResult:
    chunk_id: str = ""
    risk_level: str = "low"   # low | medium | high
    matched_patterns: list = None
    summary_only: bool = False
    blocked: bool = False
    source: str = "rag"

    def __post_init__(self):
        if self.matched_patterns is None:
            self.matched_patterns = []


# ─── Scanner ──────────────────────────────────────────────────────────────

def scan_chunk(content: str, chunk_id: str = "", source: str = "rag",
               source_type: str = "") -> InjectionScanResult:
    """Scan a single chunk for prompt injection patterns.

    Returns a result with risk level and action recommendation:
    - low: safe to inject full content
    - medium: inject summary only
    - high: block content, only record warning

    source_type adjusts scan sensitivity:
    - "knowledge": only HIGH_RISK_PATTERNS (user-curated content, trusted)
    - "" (default): full scan with HIGH + MEDIUM patterns
    """
    if not content:
        return InjectionScanResult(chunk_id=chunk_id, source=source)

    text = content.lower()
    high_matches = []
    medium_matches = []

    for pattern in HIGH_RISK_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            high_matches.append(match.group(0)[:100])

    # Skip MEDIUM_RISK_PATTERNS for knowledge content (user-curated, trusted)
    if source_type != "knowledge":
        for pattern in MEDIUM_RISK_PATTERNS:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                medium_matches.append(match.group(0)[:100])

    if high_matches:
        return InjectionScanResult(
            chunk_id=chunk_id,
            risk_level="high",
            matched_patterns=high_matches,
            blocked=True,
            source=source,
        )
    elif medium_matches:
        return InjectionScanResult(
            chunk_id=chunk_id,
            risk_level="medium",
            matched_patterns=medium_matches,
            summary_only=True,
            source=source,
        )

    return InjectionScanResult(chunk_id=chunk_id, source=source)


def scan_chunks(chunks: list, source: str = "rag", source_type: str = "") -> dict:
    """Scan multiple chunks and return filtered results.

    Returns: {
        "safe_chunks": [...],       # low risk — full content
        "summary_chunks": [...],    # medium risk — summary only, sanitized
        "blocked_chunks": [...],    # high risk — blocked (or medium that can't be sanitized)
        "warnings": [...],          # all warnings
    }

    source_type adjusts scan sensitivity:
    - "knowledge": only HIGH_RISK_PATTERNS (user-curated, trusted)
    - "" (default): full scan with HIGH + MEDIUM patterns
    """
    result = {"safe_chunks": [], "summary_chunks": [], "blocked_chunks": [], "warnings": []}

    for chunk in chunks:
        content = chunk.get("content") or chunk.get("text") or chunk.get("snippet") or ""
        cid = chunk.get("chunk_id") or chunk.get("id") or ""

        scan = scan_chunk(content, chunk_id=cid, source=source, source_type=source_type)

        if scan.blocked:
            result["blocked_chunks"].append({"chunk_id": cid, "patterns": scan.matched_patterns})
            result["warnings"].append(f"BLOCKED chunk {cid}: injection risk HIGH — {scan.matched_patterns}")
        elif scan.summary_only:
            # v2.3.1-p1: sanitize medium risk summary
            safe_summary = _sanitize_medium_summary(content, scan.matched_patterns)
            if safe_summary is None:
                # Can't sanitize — downgrade to blocked
                result["blocked_chunks"].append({"chunk_id": cid, "patterns": scan.matched_patterns})
                result["warnings"].append(f"BLOCKED chunk {cid}: injection risk MEDIUM (unsanitizable) — {scan.matched_patterns}")
            else:
                result["summary_chunks"].append({
                    "chunk_id": cid,
                    "summary": safe_summary,
                    "source": source,
                    "risk": "medium",
                })
                result["warnings"].append(f"SUMMARIZED chunk {cid}: injection risk MEDIUM — {scan.matched_patterns}")
        else:
            result["safe_chunks"].append(chunk)

    return result


def _sanitize_medium_summary(content: str, matched_patterns: list) -> str | None:
    """Generate a safe summary of medium-risk content.
    
    Returns a sanitized summary string, or None if the content cannot be safely summarized.
    A safe summary must NOT contain any of the matched injection patterns.
    """
    if not content:
        return None

    # Remove lines containing injection patterns
    lines = content.split("\n")
    safe_lines = []
    for line in lines:
        line_lower = line.lower()
        is_safe = True
        for pattern in matched_patterns:
            import re as _re
            if _re.search(pattern, line_lower):
                is_safe = False
                break
        if is_safe:
            safe_lines.append(line)

    if not safe_lines:
        return None

    summary = " ".join(safe_lines)[:300]
    # Verify summary is still safe
    for pattern in matched_patterns:
        import re as _re
        if _re.search(pattern, summary.lower()):
            return None

    return summary


def scan_text_any_source(content: str, source: str = "unknown", content_id: str = "",
                         source_type: str = "") -> InjectionScanResult:
    """Universal entry point for scanning any text content before injection.

    Use this for: memory_hits, loaded_skills_section, workspace file content,
    artifact content, web page summaries, tool results, skill prompts.
    """
    return scan_chunk(content, chunk_id=content_id, source=source, source_type=source_type)


def scan_tool_result_payload(payload: dict, tool_id: str = "", source: str = "tool_output",
                             source_type: str = "") -> dict:
    """Scan a tool result payload before appending to messages.

    Returns a sanitized payload dict:
    - high risk → minimal summary only
    - low risk → pass through unchanged

    Note: MEDIUM patterns (instruction:, command:) are intentionally NOT
    scanned here — they cause excessive false positives on legitimate tool
    output (network config tutorials, how-to pages). Only HIGH risk patterns
    (explicit injection attempts like "ignore previous instructions") are used.
    """
    # Tool payloads frequently place evidence under data/results/items. Walk
    # the structure with strict bounds so nested injection text is not missed
    # while large packet/log payloads remain cheap to scan.
    text_parts: list[str] = []
    remaining_chars = 100_000

    def collect(value, *, depth: int = 0) -> None:
        nonlocal remaining_chars
        if remaining_chars <= 0 or depth > 5:
            return
        if isinstance(value, str):
            if value:
                chunk = value[:remaining_chars]
                text_parts.append(chunk)
                remaining_chars -= len(chunk)
            return
        if isinstance(value, dict):
            for nested in value.values():
                collect(nested, depth=depth + 1)
                if remaining_chars <= 0:
                    break
            return
        if isinstance(value, (list, tuple)):
            for nested in value[:200]:
                collect(nested, depth=depth + 1)
                if remaining_chars <= 0:
                    break

    collect(payload)

    combined = "\n".join(text_parts)
    if not combined:
        return payload  # no text to scan

    # Tool result path: strict HIGH-only scan
    for pattern in HIGH_RISK_PATTERNS:
        if re.search(pattern, combined, re.IGNORECASE):
            return {
                "ok": False,
                "summary": "[blocked — injection risk detected in tool output]",
                "error": f"Injection scan blocked tool output from {tool_id}",
                "scan_result": "blocked",
            }

    return payload  # safe — pass through
