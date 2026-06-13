"""v2.0 Phase 2: Deterministic context compaction — no LLM summarization.

Strategy:
- Keep recent 6 messages intact
- Older messages replaced with deterministic summaries
- Tool results: keep ok/summary/tool_id/artifacts/source_count/manual_review_count/errors/warnings
- Strip secrets/tokens/passwords/api_keys/source_config/raw_config
- Never compact system prompt or current user message
- Returns compaction metadata
"""

from __future__ import annotations

import json
from typing import Any

# ── Forbidden keys in any compacted context ──
FORBIDDEN_KEYS = {
    "secret", "password", "token", "api_key", "private_key",
    "source_config", "raw_config", "ssh_key", "credentials",
}


def estimate_context_size(messages: list) -> int:
    """Estimate token count for a list of messages (char // 4 approximation)."""
    total = 0
    for msg in (messages or []):
        content = ""
        if isinstance(msg, str):
            content = msg
        elif isinstance(msg, dict):
            content = str(msg.get("content", ""))
        elif hasattr(msg, "content"):
            content = str(getattr(msg, "content", ""))
        total += max(1, len(content) // 4)
    return max(1, total)


def compact_tool_result_content(content: str, max_chars: int = 4000) -> str:
    """Compact a tool result JSON string: keep safe keys, strip forbidden keys."""
    if not content:
        return content
    if len(content) <= max_chars:
        # Still strip secrets even if under size budget
        return _strip_forbidden(content)
    try:
        data = json.loads(content) if isinstance(content, str) else content
    except (json.JSONDecodeError, TypeError):
        return _strip_forbidden(content[:max_chars])

    if isinstance(data, dict):
        safe = {}
        for k, v in data.items():
            if k in FORBIDDEN_KEYS:
                safe[k] = "[REDACTED]"
            elif k in ("ok", "summary", "tool_id", "artifacts",
                        "source_count", "manual_review_count",
                        "errors", "warnings"):
                safe[k] = v
            elif len(safe) < 10:
                sv = str(v)
                if len(sv) > 200:
                    sv = sv[:197] + "..."
                safe[k] = sv
        result = json.dumps(safe, ensure_ascii=False)
        return result[:max_chars]
    return _strip_forbidden(str(data)[:max_chars])


def _strip_forbidden(text: str) -> str:
    """Remove lines containing forbidden patterns."""
    if not text:
        return text
    lines = text.split("\n")
    kept = []
    for line in lines:
        low = line.lower()
        if any(fk in low for fk in FORBIDDEN_KEYS):
            kept.append("[REDACTED]")
        else:
            kept.append(line)
    return "\n".join(kept)


def _is_system_message(msg) -> bool:
    """Check if a message is a system message."""
    if isinstance(msg, dict):
        return msg.get("role") == "system"
    return hasattr(msg, "role") and getattr(msg, "role", "") == "system"


def _is_user_message(msg) -> bool:
    if isinstance(msg, dict):
        return msg.get("role") == "user"
    return hasattr(msg, "role") and getattr(msg, "role", "") == "user"


def _message_content(msg) -> str:
    if isinstance(msg, str):
        return msg
    if isinstance(msg, dict):
        return str(msg.get("content", ""))
    if hasattr(msg, "content"):
        return str(getattr(msg, "content", ""))
    return str(msg)


def compact_messages(messages: list, keep_recent: int = 6) -> tuple[list, dict]:
    """Compact message list.

    Returns (compacted_messages, metadata).
    - Keeps system messages intact
    - Keeps most recent keep_recent messages intact
    - Replaces older non-system messages with deterministic summaries
    - Never compacts the last user message
    """
    if not messages or len(messages) <= keep_recent:
        return messages, {"compacted": False, "reason": "below_threshold"}

    # Find the user message position (must not be compacted)
    user_positions = [
        i for i, m in enumerate(messages)
        if _is_user_message(m)
    ]
    # Protect the last user message
    protected_indices = set()
    if user_positions:
        protected_indices.add(user_positions[-1])

    # Protect system messages
    for i, m in enumerate(messages):
        if _is_system_message(m):
            protected_indices.add(i)

    # Protect recent messages
    recent_start = max(0, len(messages) - keep_recent)
    for i in range(recent_start, len(messages)):
        protected_indices.add(i)

    original_est = estimate_context_size(messages)

    compacted = []
    compacted_count = 0

    for i, msg in enumerate(messages):
        if i in protected_indices:
            compacted.append(msg)
        else:
            # Replace with deterministic summary
            summary = _build_deterministic_summary(msg)
            compacted.append(summary)
            compacted_count += 1

    new_est = estimate_context_size(compacted)

    return compacted, {
        "compacted": True,
        "compacted_message_count": compacted_count,
        "original_estimated_tokens": original_est,
        "compacted_estimated_tokens": new_est,
    }


def _build_deterministic_summary(msg) -> dict:
    """Build a short deterministic summary of a message."""
    role = "unknown"
    content = ""
    if isinstance(msg, dict):
        role = msg.get("role", "unknown")
        content = str(msg.get("content", ""))
    elif hasattr(msg, "role"):
        role = getattr(msg, "role", "unknown")
        content = str(getattr(msg, "content", ""))

    # Build a short summary
    preview = content[:150]

    if role == "tool":
        # Tool result: try to parse the JSON
        summary = _summarize_tool_content(content)
        return {
            "role": "tool",
            "content": f"[compacted tool result] {summary}",
        }
    elif role == "assistant":
        snippet = preview[:100].replace("\n", " ")
        return {
            "role": "assistant",
            "content": f"[compacted assistant turn: {snippet}]",
        }
    elif role == "user":
        snippet = preview[:100].replace("\n", " ")
        return {
            "role": "user",
            "content": f"[compacted user: {snippet}]",
        }
    return {"role": role, "content": f"[compacted {role} message]"}


def _summarize_tool_content(content: str) -> str:
    """Create a brief summary of a tool result."""
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            ok = data.get("ok", None)
            summary = str(data.get("summary", ""))[:100]
            return f"ok={ok} {summary}"
    except (json.JSONDecodeError, TypeError):
        pass
    return content[:80]


def should_compact(messages: list, max_context_tokens: int = 128000,
                   threshold: float = 0.75) -> bool:
    """Check if compaction is needed."""
    est = estimate_context_size(messages)
    return est > max_context_tokens * threshold


def compact_tool_result_payload(payload: dict, max_chars: int = 4000) -> dict:
    """Compact a single tool result payload for safe transmission.

    Always keeps: ok, summary, tool_id, artifacts, source_count,
    manual_review_count, errors, warnings.
    Strips forbidden keys.
    """
    safe = {
        k: payload.get(k) for k in (
            "ok", "summary", "tool_id",
            "source_count", "manual_review_count",
            "errors", "warnings",
        )
        if k in payload
    }
    if "artifacts" in payload:
        arts = payload["artifacts"]
        if isinstance(arts, list):
            safe["artifacts"] = [
                {"artifact_id": a.get("artifact_id", "")} if isinstance(a, dict) else str(a)
                for a in arts[:3]
            ]

    # Copy remaining safe keys up to 10 total
    for k, v in payload.items():
        if k in safe:
            continue
        if k in FORBIDDEN_KEYS:
            safe[k] = "[REDACTED]"
        elif len(safe) < 10:
            sv = str(v)
            if len(sv) > max_chars // 4:
                sv = sv[:max_chars // 4 - 3] + "..."
            safe[k] = sv

    return safe
