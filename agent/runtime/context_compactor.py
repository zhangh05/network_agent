"""v2.0 Phase 2 → v3.3 Long-task optimization: Deterministic context compaction.

Strategy:
- Keep recent 15 messages intact (was 6)
- Older messages replaced with structured summaries preserving key fields
- Tool results: keep ok/summary/tool_id/artifacts/source_count/manual_review_count/
  errors/warnings, PLUS: output/result/devices/hosts/assets/version/model/status
  (critical data needed for long-running analytical tasks)
- Strip secrets/tokens/passwords/api_keys/source_config/raw_config
- Never compact system prompt or current user message
- Returns compaction metadata

v3.1.1: CompactionStrategy enum + structured metrics
- fast_eviction: deterministic summary replacement (default, sub-ms)
- llm_summary: LLM-based summarization (slower, higher quality, optional)

v3.3: PRESERVE_KEYS expanded for long-task data retention.
"""

from __future__ import annotations

import enum
import json
import time
from typing import Any

# ── Forbidden keys in any compacted context ──
FORBIDDEN_KEYS = {
    "secret", "password", "token", "api_key", "private_key",
    "source_config", "raw_config", "ssh_key", "credentials",
}

# ── v3.3: Keys to always preserve in compacted tool results ──
# (data critical for long-running analytical/network tasks)
_PRESERVE_KEYS = {
    "ok", "summary", "tool_id", "artifacts",
    "source_count", "manual_review_count",
    "errors", "warnings",
    # Long-task data: CMDB, network, pcap, config
    "output", "result", "devices", "hosts", "assets",
    "version", "model", "status", "region",
    "host", "port", "protocol", "device_type",
    # Workflow / task state
    "task_id", "workflow_id", "step_id", "progress",
}


class CompactionStrategy(str, enum.Enum):
    """Strategy used to compact history.

    - fast_eviction: replace old messages with deterministic summaries
                     (no LLM call, ~0ms, used by default in token_manager).
    - llm_summary:   call LLM to summarize older messages into a coherent
                     paragraph (slower, higher quality, opt-in).
    """
    FAST_EVICTION = "fast_eviction"
    LLM_SUMMARY = "llm_summary"


class CompactionMetric:
    """Structured metric record for a single compaction event.

    Designed to be JSON-serializable for logs and frontend dashboards.
    """
    __slots__ = (
        "strategy",
        "trigger",            # "auto" | "manual"
        "threshold_pct",      # e.g. 75.0
        "original_messages",
        "original_estimated_tokens",
        "compacted_messages",
        "compacted_estimated_tokens",
        "compacted_message_count",
        "duration_ms",
        "reference_context_item_id",
        "ts",
    )

    def __init__(
        self,
        strategy: CompactionStrategy,
        trigger: str,
        threshold_pct: float,
        original_messages: int,
        original_estimated_tokens: int,
        compacted_messages: int,
        compacted_estimated_tokens: int,
        compacted_message_count: int,
        duration_ms: int,
        reference_context_item_id: str = "",
        ts: str = "",
    ) -> None:
        self.strategy = strategy
        self.trigger = trigger
        self.threshold_pct = threshold_pct
        self.original_messages = original_messages
        self.original_estimated_tokens = original_estimated_tokens
        self.compacted_messages = compacted_messages
        self.compacted_estimated_tokens = compacted_estimated_tokens
        self.compacted_message_count = compacted_message_count
        self.duration_ms = int(round(duration_ms))
        self.reference_context_item_id = reference_context_item_id
        self.ts = ts

    @property
    def retention_ratio(self) -> float:
        if self.original_estimated_tokens <= 0:
            return 0.0
        return round(self.compacted_estimated_tokens / self.original_estimated_tokens, 3)

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy.value,
            "trigger": self.trigger,
            "threshold_pct": self.threshold_pct,
            "original_messages": self.original_messages,
            "original_estimated_tokens": self.original_estimated_tokens,
            "compacted_messages": self.compacted_messages,
            "compacted_estimated_tokens": self.compacted_estimated_tokens,
            "compacted_message_count": self.compacted_message_count,
            "duration_ms": self.duration_ms,
            "reference_context_item_id": self.reference_context_item_id,
            "retention_ratio": self.retention_ratio,
            "ts": self.ts,
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
            elif k in _PRESERVE_KEYS:
                safe[k] = v
            elif len(safe) < 15:
                sv = str(v)
                if len(sv) > 200:
                    sv = sv[:197] + "..."
                safe[k] = sv
        result = json.dumps(safe, ensure_ascii=False)
        return result[:max_chars]
    return _strip_forbidden(str(data)[:max_chars])


def _strip_forbidden(text: str) -> str:
    """Remove lines containing forbidden *key* patterns (not substring matches)."""
    if not text:
        return text
    import re
    lines = text.split("\n")
    kept = []
    for line in lines:
        low = line.lower()
        # Only redact lines where forbidden key appears as a field name (k=v or "k":)
        if any(re.search(rf'\b{fk}\s*[=:]', low) for fk in FORBIDDEN_KEYS):
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


def compact_messages(
    messages: list,
    keep_recent: int = 15,
    strategy: CompactionStrategy = CompactionStrategy.FAST_EVICTION,
    trigger: str = "auto",
    threshold_pct: float = 75.0,
) -> tuple[list, dict]:
    """Compact message list.

    Returns (compacted_messages, metadata). metadata includes:
      - strategy: CompactionStrategy used
      - trigger: "auto" | "manual"
      - threshold_pct: trigger threshold at the time of compaction
      - compacted_message_count: how many messages were replaced
      - original_estimated_tokens / compacted_estimated_tokens
      - reference_context_item_id: id of the first kept message (context anchor)
      - duration_ms: time spent compacting
      - retention_ratio: compacted/original token ratio

    Rules:
    - Keeps system messages intact
    - Keeps most recent keep_recent messages intact
    - Replaces older non-system messages with deterministic summaries
    - Never compacts the last user message
    """
    from datetime import datetime, timezone

    t0 = time.perf_counter()
    if not messages or len(messages) <= keep_recent:
        return messages, {
            "compacted": False,
            "reason": "below_threshold",
            "strategy": strategy.value,
            "duration_ms": int(round((time.perf_counter() - t0) * 1000)),
        }

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

    if strategy == CompactionStrategy.LLM_SUMMARY:
        protected_messages = [m for i, m in enumerate(messages) if i in protected_indices]
        old_messages = [m for i, m in enumerate(messages) if i not in protected_indices]
        summary = _build_progress_summary(old_messages)
        compacted = [summary, *protected_messages] if summary else protected_messages
        new_est = estimate_context_size(compacted)
        duration_ms = int(round((time.perf_counter() - t0) * 1000))
        return compacted, {
            "compacted": True,
            "strategy": strategy.value,
            "trigger": trigger,
            "threshold_pct": threshold_pct,
            "compacted_message_count": len(old_messages),
            "original_estimated_tokens": original_est,
            "compacted_estimated_tokens": new_est,
            "duration_ms": duration_ms,
            "reference_context_item_id": _first_reference_id(compacted),
            "retention_ratio": round(new_est / original_est, 3) if original_est > 0 else 0.0,
            "summary_message_created": bool(summary),
            "summary_source": "deterministic_fallback",
            "ts": datetime.now(timezone.utc).isoformat(),
        }

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
    duration_ms = int(round((time.perf_counter() - t0) * 1000))

    return compacted, {
        "compacted": True,
        "strategy": strategy.value,
        "trigger": trigger,
        "threshold_pct": threshold_pct,
        "compacted_message_count": compacted_count,
        "original_estimated_tokens": original_est,
        "compacted_estimated_tokens": new_est,
        "duration_ms": duration_ms,
        "reference_context_item_id": _first_reference_id(compacted),
        "retention_ratio": round(new_est / original_est, 3) if original_est > 0 else 0.0,
        "summary_message_created": False,
        "ts": datetime.now(timezone.utc).isoformat(),
    }


def build_compaction_metric(
    meta: dict,
    strategy: CompactionStrategy,
    trigger: str,
    threshold_pct: float,
    original_messages: int,
    reference_context_item_id: str = "",
) -> CompactionMetric:
    """Build a CompactionMetric from compact_messages() metadata."""
    from datetime import datetime, timezone
    return CompactionMetric(
        strategy=strategy,
        trigger=trigger,
        threshold_pct=threshold_pct,
        original_messages=original_messages,
        original_estimated_tokens=int(meta.get("original_estimated_tokens", 0)),
        compacted_messages=original_messages - int(meta.get("compacted_message_count", 0)),
        compacted_estimated_tokens=int(meta.get("compacted_estimated_tokens", 0)),
        compacted_message_count=int(meta.get("compacted_message_count", 0)),
        duration_ms=int(meta.get("duration_ms", 0)),
        reference_context_item_id=meta.get("reference_context_item_id") or reference_context_item_id,
        ts=meta.get("ts", "") or datetime.now(timezone.utc).isoformat(),
    )


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


def _build_progress_summary(messages: list) -> dict:
    """Build a compact progress summary for older history."""
    snippets = []
    tool_count = 0
    user_count = 0
    assistant_count = 0
    for msg in messages or []:
        role = "unknown"
        if isinstance(msg, dict):
            role = str(msg.get("role", "unknown"))
        elif hasattr(msg, "role"):
            role = str(getattr(msg, "role", "unknown"))
        content = _message_content(msg).replace("\n", " ").strip()
        if not content:
            continue
        if role == "tool":
            tool_count += 1
        elif role == "user":
            user_count += 1
        elif role == "assistant":
            assistant_count += 1
        if len(snippets) < 8:
            snippets.append(f"- {role}: {content[:180]}")
    content = (
        "[State of progress]\n"
        f"Compacted earlier context: {len(messages or [])} messages "
        f"({user_count} user, {assistant_count} assistant, {tool_count} tool).\n"
    )
    if snippets:
        content += "Key preserved points:\n" + "\n".join(snippets)
    return {
        "role": "assistant",
        "content": content[:3000],
        "message_id": "context_summary_auto",
        "metadata": {"compaction": "llm_summary", "source": "deterministic_fallback"},
    }


def _first_reference_id(messages: list) -> str:
    """Return first non-system context item id."""
    for m in messages or []:
        if isinstance(m, dict) and not _is_system_message(m):
            mid = m.get("message_id") or m.get("id") or m.get("run_id") or ""
            if mid:
                return str(mid)
        elif hasattr(m, "message_id"):
            mid = str(getattr(m, "message_id", "") or "")
            if mid:
                return mid
    return ""


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
