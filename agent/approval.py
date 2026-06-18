"""Tool approval system — pauses agent on high-risk tool calls.

The agent loop creates an ApprovalRequest for high-risk tools and
waits.  The frontend polls /api/agent/approvals/pending, shows an
Allow/Deny dialog, and resolves via /api/agent/approvals/{id}/resolve.

v3.1: Added async/non-blocking support. The wait() method now supports
a non-blocking mode that returns immediately with a pending status.
The caller can check resolved status later via check().
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
    metadata: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    resolved: bool = False
    allowed: bool = False
    _event: threading.Event = field(default_factory=threading.Event)


class ApprovalStore:
    """In-memory approval store with thread-safe wait/resolve.

    v3.1: Supports both synchronous (blocking) and non-blocking modes.
    - wait(blocking=True): blocks up to timeout seconds (compat behavior)
    - wait(blocking=False): returns immediately; use check() to poll
    """

    def __init__(self):
        self._pending: dict[str, ApprovalRequest] = {}
        self._lock = threading.Lock()

    def create(self, session_id: str, tool_id: str,
               arguments: dict, description: str = "",
               risk_level: str = "high", metadata: dict = None) -> ApprovalRequest:
        """Create a pending approval and return it."""
        approval_id = f"apr_{uuid.uuid4().hex[:12]}"
        req = ApprovalRequest(
            approval_id=approval_id,
            session_id=session_id,
            tool_id=tool_id,
            arguments=arguments,
            description=description,
            risk_level=risk_level,
            metadata=metadata or {},
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

    def check(self, approval_id: str) -> Optional[bool]:
        """Non-blocking check: returns True/False if resolved, None if still pending."""
        with self._lock:
            req = self._pending.get(approval_id)
            if not req:
                return None
            if not req.resolved:
                return None
            return req.allowed

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
                    "arguments_preview": req.arguments,
                    "created_at": req.created_at,
                    "created_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(req.created_at)),
                    # v2.3.1-p1: risk source info for UI display
                    "argument_source": req.metadata.get("argument_source", ""),
                    "argument_risk": req.metadata.get("argument_risk", ""),
                    "reason": req.metadata.get("reason", ""),
                    "recommendation": req.metadata.get("recommendation", ""),
                })
            return result

    def wait(self, approval_id: str, timeout: float = 60.0, blocking: bool = True) -> Optional[bool]:
        """Wait for approval to be resolved.

        Args:
            approval_id: The approval to wait for.
            timeout: Maximum wait time in seconds (only for blocking mode).
            blocking: If True (default), blocks until resolved or timeout.
                      If False, returns immediately: True=allowed, False=denied, None=pending.

        Returns:
            - blocking=True: True if allowed, False if denied/timed out.
            - blocking=False: True if resolved+allowed, False if resolved+denied, None if still pending.
        """
        with self._lock:
            req = self._pending.get(approval_id)

        if not req:
            return False

        if not blocking:
            if req.resolved:
                return req.allowed
            return None

        # Blocking mode: poll in 500ms intervals
        elapsed = 0.0
        while elapsed < timeout:
            if req._event.wait(timeout=0.5):
                return req.allowed
            elapsed += 0.5

        # Timeout — auto-deny
        with self._lock:
            if not req.resolved:
                req.resolved = True
                req.allowed = False
                req._event.set()
        return False

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
