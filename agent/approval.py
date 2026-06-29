"""Unified tool approval system — single source of truth for all approvals.

ALL approval flows MUST go through ApprovalStore. There is no legacy
alternative, no dual-store pattern, no bypass.

Key guarantees:
- Every approval is bound to workspace_id + session_id (+ run_id/job_id if present)
- resolve() enforces admin token boundary when NETWORK_AGENT_ADMIN_TOKEN is set
- Arguments are redacted by default in persisted records and API responses
- SSE events are published on create/resolve for real-time frontend updates
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

from agent.runtime.utils import now_iso, to_iso, from_iso


def _now_iso() -> str:
    """v3.9.8: wrapper for ApprovalRequest default_factory."""
    return now_iso()


def _now_iso_offset(delta_seconds: float) -> str:
    """Return the ISO timestamp for ``now + delta_seconds``.

    Used by ApprovalStore._load_history to compute a retention cutoff.
    """
    target = datetime.now(timezone.utc) + timedelta(seconds=delta_seconds)
    return target.isoformat()


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
    workspace_id: str = ""
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
    workspace_id: str = ""
    run_id: str = ""
    job_id: str = ""
    metadata: dict = field(default_factory=dict)
    # v3.9.8: created_at / resolved_at are now ISO-8601 strings (UTC),
    # matching every other dataclass in the durable / state / event
    # namespace. Earlier float/epoch split made the API surface
    # inconsistent between /api/approvals and /api/agent/state.
    created_at: str = field(default_factory=_now_iso)
    resolved: bool = False
    allowed: bool = False
    resolved_at: Optional[str] = None
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
            cutoff_iso = _now_iso_offset(-_RETENTION_DAYS * 86400)
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
                    # v3.9.8: created_at is an ISO-8601 string in the
                    # JSONL log. Legacy records (pre-v3.9.8) store a
                    # float epoch — coerce via ``to_iso`` so we accept
                    # both representations during the migration window.
                    raw_created = rec.get("created_at") or ""
                    try:
                        created_iso = to_iso(raw_created)
                    except Exception:
                        continue
                    if (created_iso or "") < cutoff_iso:
                        continue
                    req = ApprovalRequest(
                        approval_id=rec["approval_id"],
                        session_id=rec.get("session_id", ""),
                        tool_id=rec.get("tool_id", ""),
                        arguments=rec.get("arguments", {}),
                        description=rec.get("description", ""),
                        risk_level=rec.get("risk_level", "high"),
                        metadata=rec.get("metadata", {}),
                        created_at=created_iso,
                        resolved=False,
                    )
                    self._pending[req.approval_id] = req
        except Exception:
            pass

    def _append_record(self, req: ApprovalRequest) -> None:
        """Append a record (pending or resolved) to the JSONL audit log."""
        try:
            from tool_runtime.redaction import redact_tool_output

            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            rec = {
                "approval_id": req.approval_id,
                "session_id": req.session_id,
                "tool_id": req.tool_id,
                "arguments": redact_tool_output(req.arguments or {}),
                "description": req.description,
                "risk_level": req.risk_level,
                "workspace_id": req.workspace_id,
                "run_id": req.run_id,
                "job_id": req.job_id,
                "metadata": redact_tool_output(req.metadata or {}),
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
               risk_level: str = "high",
               workspace_id: str = "",
               run_id: str = "",
               job_id: str = "",
               metadata: dict = None) -> ApprovalRequest:
        """Create a pending approval, persist it, and notify subscribers.

        All approval records MUST be bound to workspace_id + session_id.
        Optional run_id/job_id provide traceability when the approval
        originates from a specific agent run or job.
        """
        if not workspace_id:
            raise ValueError("workspace_id is required")
        try:
            from workspace.ids import validate_workspace_id
            workspace_id = validate_workspace_id(workspace_id)
        except Exception as exc:
            raise ValueError("invalid_workspace_id") from exc
        approval_id = f"apr_{uuid.uuid4().hex[:12]}"
        req = ApprovalRequest(
            approval_id=approval_id,
            session_id=session_id,
            tool_id=tool_id,
            arguments=arguments,
            description=description,
            risk_level=risk_level,
            workspace_id=workspace_id,
            run_id=run_id,
            job_id=job_id,
            metadata=metadata or {},
        )
        with self._lock:
            self._pending[approval_id] = req
        self._append_record(req)
        _event_bus.publish(ApprovalEvent(
            kind="created", approval_id=approval_id,
            session_id=session_id, tool_id=tool_id,
            workspace_id=workspace_id,
            payload={"risk_level": risk_level, "description": description},
        ))
        return req

    def resolve(self, approval_id: str, allowed: bool, workspace_id: str,
                resolver: str = "user", reason: str = "") -> Optional[ApprovalRequest]:
        """Resolve an approval only when approval_id belongs to workspace_id."""
        if not workspace_id:
            return None
        try:
            from workspace.ids import validate_workspace_id
            workspace_id = validate_workspace_id(workspace_id)
        except Exception:
            return None
        with self._lock:
            req = self._pending.get(approval_id)
            if req and req.workspace_id != workspace_id:
                return None
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
            workspace_id=req.workspace_id,
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

    def get_pending(self, session_id: str = "", workspace_id: str = "") -> list[dict]:
        """Get pending approvals, optionally filtered by workspace/session.

        Stale approvals (older than 120s) are auto-cleaned up during this call
        to prevent orphaned approvals from flashing the frontend bubble.
        """
        with self._lock:
            now = datetime.now(timezone.utc)
            stale_ids = []
            for aid, req in list(self._pending.items()):
                if req.resolved:
                    stale_ids.append(aid)
                    continue
                # Auto-expire approvals older than 120 seconds that never
                # reached the wait/resolve path (orphaned by turn failure).
                # v3.9.8: created_at is an ISO-8601 string now; compare
                # via datetime parsing instead of float math.
                try:
                    created = datetime.fromisoformat(req.created_at)
                    if req.created_at and (now - created).total_seconds() > 120:
                        _expire = True
                    else:
                        _expire = False
                except Exception:
                    _expire = False
                if _expire:
                    req.resolved = True
                    req.allowed = False
                    req.resolved_at = now_iso()
                    req.resolver = "system_expired"
                    req._event.set()
                    self._append_record(req)
                    _event_bus.publish(ApprovalEvent(
                        kind="resolved", approval_id=aid,
                        session_id=req.session_id, tool_id=req.tool_id,
                        workspace_id=req.workspace_id,
                        allowed=False, payload={"resolver": "system_expired"},
                    ))
                    stale_ids.append(aid)
            for aid in stale_ids:
                self._pending.pop(aid, None)

            result = []
            for req in self._pending.values():
                if workspace_id and req.workspace_id != workspace_id:
                    continue
                if session_id and req.session_id != session_id:
                    continue
                result.append(self._to_dict(req))
            return result

    def get_history(self, session_id: str = "", tool_id: str = "",
                    workspace_id: str = "",
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
                    if workspace_id and rec.get("workspace_id") != workspace_id:
                        continue
                    if session_id and rec.get("session_id") != session_id:
                        continue
                    if tool_id and rec.get("tool_id") != tool_id:
                        continue
                    if since_ts and rec.get("created_at", "") < since_ts:
                        continue
                    records.append(rec)
        except Exception:
            return []
        records.sort(key=lambda r: r.get("resolved_at") or "", reverse=True)
        return records[:limit]

    def wait(self, approval_id: str, timeout: int = 60,
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
                    workspace_id=req.workspace_id,
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
        from tool_runtime.redaction import redact_tool_output

        safe_arguments = redact_tool_output(req.arguments or {})
        # v3.9.8: created_at is an ISO string now (was float). Both
        # ``created_at`` and ``created_at_iso`` carry the same value;
        # callers should pick one and stick with it.
        created_at = req.created_at
        if not created_at:
            created_at = now_iso()
        return {
            "approval_id": req.approval_id,
            "session_id": req.session_id,
            "tool_id": req.tool_id,
            "workspace_id": req.workspace_id,
            "run_id": req.run_id,
            "job_id": req.job_id,
            "description": req.description,
            "risk_level": req.risk_level,
            "status": "resolved" if req.resolved else "pending",
            "arguments_summary": _summarize_args(safe_arguments),
            "arguments_preview": safe_arguments,
            "created_at": created_at,
            "created_at_iso": created_at,
        }


def _summarize_args(args: dict) -> str:
    """Summarize tool arguments for display."""
    from tool_runtime.redaction import redact_tool_output

    items = []
    for k, v in (redact_tool_output(args or {}) or {}).items():
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
        with _get_lock():
            if _approval_store is None:
                _approval_store = ApprovalStore()
    return _approval_store

_appr_lock = None
def _get_lock():
    global _appr_lock
    if _appr_lock is None:
        import threading
        _appr_lock = threading.Lock()
    return _appr_lock


def reset_approval_store_for_tests(remove_persisted: bool = False) -> None:
    """Reset the module-level approval store for isolated tests."""
    global _approval_store
    if _approval_store is not None:
        with _approval_store._lock:
            _approval_store._pending.clear()
    if remove_persisted:
        try:
            (_approval_store._persist_path if _approval_store else _APPROVALS_FILE).unlink(missing_ok=True)
        except Exception:
            pass
    _approval_store = None
