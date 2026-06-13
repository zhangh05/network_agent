"""Tool approval system — pauses agent on high-risk tool calls.

The agent loop creates an ApprovalRequest for high-risk tools and
waits.  The frontend polls /api/agent/approvals/pending, shows an
Allow/Deny dialog, and resolves via /api/agent/approvals/{id}/resolve.
"""

from __future__ import annotations

import uuid
import time
import threading
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ApprovalRequest:
    approval_id: str
    session_id: str
    tool_id: str
    arguments: dict
    description: str
    risk_level: str
    created_at: float = field(default_factory=time.time)
    resolved: bool = False
    allowed: bool = False
    _event: threading.Event = field(default_factory=threading.Event)


class ApprovalStore:
    """In-memory approval store with thread-safe wait/resolve."""

    def __init__(self):
        self._pending: dict[str, ApprovalRequest] = {}
        self._lock = threading.Lock()

    def create(self, session_id: str, tool_id: str,
               arguments: dict, description: str = "",
               risk_level: str = "high") -> ApprovalRequest:
        """Create a pending approval and return it."""
        approval_id = f"apr_{uuid.uuid4().hex[:12]}"
        req = ApprovalRequest(
            approval_id=approval_id,
            session_id=session_id,
            tool_id=tool_id,
            arguments=arguments,
            description=description,
            risk_level=risk_level,
        )
        with self._lock:
            self._pending[approval_id] = req
        return req

    def resolve(self, approval_id: str, allowed: bool) -> Optional[ApprovalRequest]:
        """Resolve an approval — allow or deny."""
        with self._lock:
            req = self._pending.get(approval_id)
            if req and not req.resolved:
                req.resolved = True
                req.allowed = allowed
                req._event.set()
                return req
        return None

    def get_pending(self, session_id: str = "") -> list[dict]:
        """Get pending approvals, optionally filtered by session."""
        with self._lock:
            result = []
            for req in self._pending.values():
                if req.resolved:
                    continue
                if session_id and req.session_id != session_id:
                    continue
                result.append({
                    "approval_id": req.approval_id,
                    "session_id": req.session_id,
                    "tool_id": req.tool_id,
                    "description": req.description,
                    "risk_level": req.risk_level,
                    "arguments_summary": _summarize_args(req.arguments),
                    "created_at": req.created_at,
                })
            return result

    def wait(self, approval_id: str, timeout: float = 120.0) -> bool:
        """Wait for approval to be resolved. Returns True if allowed."""
        with self._lock:
            req = self._pending.get(approval_id)
        if not req:
            return False
        req._event.wait(timeout=timeout)
        return req.allowed

    def cleanup(self, approval_id: str):
        with self._lock:
            self._pending.pop(approval_id, None)


def _summarize_args(args: dict) -> str:
    """Summarize tool arguments for display."""
    items = []
    for k, v in (args or {}).items():
        s = str(v)
        if len(s) > 80:
            s = s[:77] + "..."
        items.append(f"{k}={s}")
    return ", ".join(items[:5])


# Singleton
_approval_store: Optional[ApprovalStore] = None


def get_approval_store() -> ApprovalStore:
    global _approval_store
    if _approval_store is None:
        _approval_store = ApprovalStore()
    return _approval_store
