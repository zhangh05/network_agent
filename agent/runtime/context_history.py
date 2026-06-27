# agent/runtime/context_history.py
"""History context helpers for TurnContext construction and runtime hydration."""

from __future__ import annotations

import json
import logging
from typing import Any

from agent.protocol.message import UserMessage, AssistantMessage, ToolResultMessage

_log = logging.getLogger(__name__)


DEFAULT_HISTORY_WINDOW = 30

def initial_history_window(session: Any, k: int = DEFAULT_HISTORY_WINDOW) -> list:
    """Return the in-memory session history window.

    This is intentionally lightweight and side-effect free. Disk hydration is
    handled by `hydrate_history_from_store()` when the runtime has a complete
    context object.

    v3.3 (long-task optimization): default window raised from 8→30 to preserve
    context across 20+ turn sessions without loss.
    """
    try:
        history = getattr(session, "history", None) or []
        return list(history[-k:]) if history else []
    except Exception:
        return []


def hydrate_history_from_store(session: Any, context: Any, k: int = DEFAULT_HISTORY_WINDOW) -> None:
    """Merge disk-persisted messages into `context.history_window`.

    The SessionMessageStore is the durable source of truth, while
    session.history is an in-memory cache that may contain not-yet-flushed
    messages. This helper keeps the merge logic in one place so loop.py does
    not own persistence details.
    """
    try:
        from workspace.message_store import SessionMessageStore

        store = SessionMessageStore(
            session_id=session.session_id,
            ws_id=session.workspace_id or "",
        )
        memory_msgs = initial_history_window(session, k=k)
        memory_ids = {
            getattr(m, "id", getattr(m, "message_id", None))
            for m in memory_msgs
            if hasattr(m, "id") or hasattr(m, "message_id")
        }

        if store.exists():
            raw_messages = _read_store_messages(store, k)
            if raw_messages:
                msgs = _project_store_messages(raw_messages)
                seen = {
                    m.get("message_id") or m.get("id") or m.get("content", "")[:40]
                    for m in raw_messages if isinstance(m, dict)
                }
                for mm in memory_msgs:
                    mid = getattr(mm, "id", getattr(mm, "message_id", None))
                    if mid and mid in memory_ids and mid not in seen:
                        msgs.append(mm)
                context.history_window = _compact_history_window(msgs, k, context)
        elif memory_msgs:
            context.history_window = memory_msgs
    except Exception as e:
        _log.warning(
            "Failed to hydrate history_window from SessionMessageStore for %s: %s",
            getattr(session, "session_id", ""),
            e,
        )


def _read_store_messages(store: Any, k: int) -> list[dict]:
    """Read full history when available so old turns can be compacted."""
    try:
        all_messages = store.get_messages()
        if len(all_messages) > k:
            return all_messages
    except Exception:
        pass
    try:
        return store.get_history_window(k=k)
    except Exception:
        return []


def _project_store_messages(raw_messages: list[dict]) -> list:
    msgs = []
    seen = set()
    for m in raw_messages:
        if not isinstance(m, dict):
            continue
        mid = m.get("message_id") or m.get("id") or m.get("content", "")[:40]
        if mid and mid in seen:
            continue
        seen.add(mid)
        role = m.get("role", "")
        content = m.get("content", "")
        if role == "user":
            msgs.append(UserMessage(content=content))
        elif role == "assistant":
            msgs.append(AssistantMessage(content=content))
        elif role == "tool":
            msgs.append(ToolResultMessage(
                content=json.dumps({"ok": m.get("ok", False), "summary": content[:500]}, ensure_ascii=False),
                tool_call_id=m.get("tool_call_id", m.get("id", "")),
            ))
    return msgs


def _compact_history_window(messages: list, k: int, context: Any) -> list:
    if len(messages) <= k:
        return messages[-k:]
    try:
        from agent.runtime.context_compactor import CompactionStrategy, compact_messages
        compacted, meta = compact_messages(
            messages,
            keep_recent=max(2, k // 2),
            strategy=CompactionStrategy.FAST_EVICTION,
            trigger="auto",
            threshold_pct=0.0,
        )
        if hasattr(context, "metadata") and isinstance(context.metadata, dict):
            context.metadata["history_compaction"] = meta
        return compacted[-k:]
    except Exception as exc:
        if hasattr(context, "metadata") and isinstance(context.metadata, dict):
            context.metadata["history_compaction"] = {"compacted": False, "error": str(exc)[:120]}
        return messages[-k:]
