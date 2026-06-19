# backend/api/agent_contract.py
"""Shared helpers for agent HTTP/WebSocket transports."""

from __future__ import annotations

import json
from typing import Any


def metadata_size(value: Any) -> int:
    try:
        return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))
    except Exception:
        return 0
