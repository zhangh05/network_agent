"""Tool approval system — pauses agent on high-risk tool calls.

The agent loop creates an ApprovalRequest for high-risk tools and
waits.  The frontend polls /api/agent/approvals/pending, shows an
Allow/Deny dialog, and resolves via /api/agent/approvals/{id}/resolve.

v3.1.0: Added async/non-blocking support. The wait() method now supports
a non-blocking mode that returns immediately with a pending status.
The caller can check resolved status later via check().

v3.2.0 (Guardian): Persisted approvals + audit history.
- Pending requests are persisted to data/tool_approvals.jsonl
- Resolved requests are kept for 90 days as audit history
- ApprovalRouter.publish() emits events to in-process subscribers (SSE bridge)
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# ════════════════════════════════════════════════════
# Constants
# ════════════════════════════════════════════════════

# Resolve data directory relative to project root
_ROOT = Path(__file__).resolve().parent.parent
_DATA_DIR = _ROOT / "data"
_APPROVALS_FILE = _DATA_DIR / "tool_approvals.jsonl"
_RETENTION_DAYS = 90
_GC_INTERVAL_SECONDS = 600  # 10 minutes

# ════════════════════════════════════════════════════
# Event subscription (SSE bridge)
# ════════════════════════════════════════════════════


@dataclass
class ApprovalEvent:
    """Real-time event emitted on approval state changes."""
    kind: str           # "created" | "resolved"
    approval_id: str
    session_id: str
    tool_id: str
    allowed: bool = False
    payload: Dict[str, Any] = field(default_factory=dict)


class _EventBus:
    """Thread-safe pub/sub for approval events.

    Subscribers receive ApprovalEvent on create/resolve. The Guardian SSE
    endpoint forwards each event to the connected frontend clients.
    """

    def __init__(self) -> None:
        self._subscribers: List[Callable[[ApprovalEvent], None]] = []
        self._lock = threading.Lock()

    def subscribe(self, fn: Callable[[ApprovalEvent], None]) -> Callable[[], None]:
        with self._lock:
            self._subscribers.append(fn)

        def unsubscribe() -> None:
            with self._lock:
                try:
                    self._subscribers.remove(fn)
                except ValueError:
                    pass

        return unsubscribe

    def publish(self, event: ApprovalEvent) -> None:
        with self._lock:
            subs = list(self._subscribers)
        for fn in subs:
            try:
                fn(event)
            except Exception:
                pass  # one bad subscriber must not break others


# Module-level singleton (separate from store so SSE routes can import it
# without pulling in the full approval flow).
_event_bus = _EventBus()


def get_event_bus() -> _EventBus:
    return _event_bus


# ════════════════════════════════════════════════════
# Approval request & store
# ════════════════════════════════════════════════════


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
    resolved_at: Optional[float] = None
    resolver: str = ""              # who resolved (user/admin/system)
    reason: str = ""                # resolver's optional note
    _event: threading.Event = field(default_factory=threading.Event)


class ApprovalStore:
    """Persistent approval store with thread-safe wait/resolve.

    v3.2.0 (Guardian):
    - Pending requests: kept in-memory + appended to JSONL
    - Resolved requests: appended to JSONL, kept for _RETENTION_DAYS
    - Subscribers receive real-time events on create/resolve
    """

    def __init__(self, persist_path: Optional[Path] = None) -> None:
        self._pending: dict[str, ApprovalRequest] = {}
        self._lock = threading.Lock()
        self._persist_path = Path(persist_path) if persist_path else _APPROVALS_FILE
        self._last_gc_at: float = 0.0
        self._load_history()

    # ── File I/O ────────────────────────────────────────────────────

    def _load_history(self) -> None:
        """Reload recent unresolved approvals from disk on startup."""
        if not self._persist_path.exists():
            return
        try:
            cutoff = time.time() - _RETENTION_DAYS * 86400
            with self._persist_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    # Only restore still-pending records (resolved are history)
                    if rec.get("resolved"):
                        continue
                    if rec.get("created_at", 0) < cutoff:
                        continue
                    req = ApprovalRequest(
                        approval_id=rec["approval_id"],
                        session_id=rec.get("session_id", ""),
                        tool_id=rec.get("tool_id", ""),
                        arguments=rec.get("arguments", {}),
                        description=rec.get("description", ""),
                        risk_level=rec.get("risk_level", "high"),
                        metadata=rec.get("metadata", {}),
                        created_at=rec.get("created_at", time.time()),
                        resolved=False,
                    )
                    self._pending[req.approval_id] = req
        except Exception:
            pass

    def _append_record(self, req: ApprovalRequest) -> None:
        """Append a record (pending or resolved) to the JSONL audit log."""
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            rec = {
                "approval_id": req.approval_id,
                "session_id": req.session_id,
                "tool_id": req.tool_id,
                "arguments": req.arguments,
                "description": req.description,
                "risk_level": req.risk_level,
                "metadata": req.metadata,
                "created_at": req.created_at,
                "resolved": req.resolved,
                "allowed": req.allowed if req.resolved else None,
                "resolved_at": req.resolved_at,
                "resolver": req.resolver,
                "reason": req.reason,
            }
            with self._persist_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _gc_history(self) -> None:
        """Periodically compact the audit log by removing records older than retention."""
        now = time.time()
        if now - self._last_gc_at < _GC_INTERVAL_SECONDS:
            return
        if not self._persist_path.exists():
            return
        self._last_gc_at = now
        cutoff = now - _RETENTION_DAYS * 86400
        try:
            kept: List[str] = []
            with self._persist_path.open("r", encoding="utf-8") as f:
                for line in f:
                    try:
                        rec = json.loads(line.strip())
                    except Exception:
                        continue
                    if rec.get("created_at", 0) >= cutoff:
                        kept.append(line if line.endswith("\n") else line + "\n")
            tmp = self._persist_path.with_suffix(".jsonl.tmp")
            with tmp.open("w", encoding="utf-8") as f:
                f.writelines(kept)
            tmp.replace(self._persist_path)
        except Exception:
            pass

    # ── Public API ──────────────────────────────────────────────────

    def create(self, session_id: str, tool_id: str,
               arguments: dict, description: str = "",
               risk_level: str = "high", metadata: dict = None) -> ApprovalRequest:
        """Create a pending approval, persist it, and notify subscribers."""
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
        self._append_record(req)
        _event_bus.publish(ApprovalEvent(
            kind="created", approval_id=approval_id,
            session_id=session_id, tool_id=tool_id,
            payload={"risk_level": risk_level, "description": description},
        ))
        return req

    def resolve(self, approval_id: str, allowed: bool,
                resolver: str = "user", reason: str = "") -> Optional[ApprovalRequest]:
        """Resolve an approval and notify subscribers."""
        with self._lock:
            req = self._pending.get(approval_id)
            if req and not req.resolved:
                req.resolved = True
                req.allowed = allowed
                req.resolved_at = time.time()
                req.resolver = resolver
                req.reason = reason
                req._event.set()
        if req is None:
            return None
        self._append_record(req)
        self._gc_history()
        _event_bus.publish(ApprovalEvent(
            kind="resolved", approval_id=approval_id,
            session_id=req.session_id, tool_id=req.tool_id,
            allowed=allowed, payload={"resolver": resolver, "reason": reason},
        ))
        # Pending entries can be freed once resolved — they live on in JSONL.
        with self._lock:
            self._pending.pop(approval_id, None)
        return req

    def check(self, approval_id: str) -> Optional[bool]:
        """Non-blocking check: True=allowed, False=denied, None=pending."""
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
                result.append(self._to_dict(req))
            return result

    def get_history(self, session_id: str = "", tool_id: str = "",
                    limit: int = 100, since_ts: float = 0.0) -> list[dict]:
        """Return resolved approvals from the audit log."""
        if not self._persist_path.exists():
            return []
        records: list[dict] = []
        try:
            with self._persist_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not rec.get("resolved"):
                        continue
                    if session_id and rec.get("session_id") != session_id:
                        continue
                    if tool_id and rec.get("tool_id") != tool_id:
                        continue
                    if since_ts and rec.get("created_at", 0) < since_ts:
                        continue
                    records.append(rec)
        except Exception:
            return []
        records.sort(key=lambda r: r.get("resolved_at") or 0, reverse=True)
        return records[:limit]

    def wait(self, approval_id: str, timeout: float = 60.0,
             blocking: bool = True) -> Optional[bool]:
        """Wait for approval to be resolved.

        Args:
            approval_id: The approval to wait for.
            timeout: Maximum wait time in seconds (only for blocking mode).
            blocking: If True, blocks until resolved or timeout. If False,
                      returns immediately: True=allowed, False=denied, None=pending.

        Returns:
            - blocking=True: True if allowed, False if denied/timed out.
            - blocking=False: True/False if resolved, None if pending.
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
                req.resolved_at = time.time()
                req.resolver = "system_timeout"
                req._event.set()
                self._append_record(req)
                _event_bus.publish(ApprovalEvent(
                    kind="resolved", approval_id=approval_id,
                    session_id=req.session_id, tool_id=req.tool_id,
                    allowed=False, payload={"resolver": "system_timeout"},
                ))
                self._pending.pop(approval_id, None)
        return False

    def cleanup(self, approval_id: str):
        with self._lock:
            self._pending.pop(approval_id, None)

    # ── Internals ───────────────────────────────────────────────────

    @staticmethod
    def _to_dict(req: ApprovalRequest) -> dict:
        return {
            "approval_id": req.approval_id,
            "session_id": req.session_id,
            "tool_id": req.tool_id,
            "description": req.description,
            "risk_level": req.risk_level,
            "arguments_summary": _summarize_args(req.arguments),
            "arguments_preview": req.arguments,
            "created_at": req.created_at,
            "created_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(req.created_at)),
            "argument_source": req.metadata.get("argument_source", ""),
            "argument_risk": req.metadata.get("argument_risk", ""),
            "reason": req.metadata.get("reason", ""),
            "recommendation": req.metadata.get("recommendation", ""),
        }


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
