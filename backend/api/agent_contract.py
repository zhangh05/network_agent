# backend/api/agent_contract.py
"""Shared helpers for agent transports."""

from __future__ import annotations

import json
from typing import Any


def metadata_size(value: Any) -> int:
    try:
        return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))
    except Exception:
        return 0


def resolve_stream_mode(data: dict) -> tuple[bool, str]:
    requested = data.get("stream_mode") or data.get("stream") or False
    if requested is True:
        return True, "event_replay"
    if requested is False or requested is None:
        return False, "sync"
    mode = str(requested).strip().lower()
    if mode in {"1", "true", "yes", "sse", "event_replay", "replay"}:
        return True, "event_replay"
    if mode in {"live", "live_stream"}:
        return True, "event_replay"
    return False, "sync"
