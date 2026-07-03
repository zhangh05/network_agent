"""Generic long-task tracking helpers for SSOT Runtime.

Any capability can surface a ``tracking`` payload. Inspection is only one
producer; the runtime and frontend consume this generic shape:

    kind=long_task, domain=<capability>, task_id=<id>, status=<state>

Retry repeats a failed action. Tracking observes an already-created long task.
"""

from __future__ import annotations

from typing import Any


def extract_tracking_payload(data: Any) -> dict[str, Any]:
    """Return a tracking payload from a nested tool result, if present."""
    if not isinstance(data, dict):
        return {}
    direct = data.get("tracking")
    if isinstance(direct, dict) and direct:
        return normalize_tracking_payload(direct)
    for key in ("output", "content", "data", "task", "result"):
        nested = data.get(key)
        if isinstance(nested, dict):
            found = extract_tracking_payload(nested)
            if found:
                return found
    return {}


def normalize_tracking_payload(tracking: dict[str, Any]) -> dict[str, Any]:
    """Normalize producer-specific tracking into the SSOT metadata contract."""
    summary = tracking.get("summary") if isinstance(tracking.get("summary"), dict) else {}
    progress = tracking.get("progress") if isinstance(tracking.get("progress"), dict) else {}
    policy = tracking.get("policy") if isinstance(tracking.get("policy"), dict) else {}
    task_id = tracking.get("task_id") or summary.get("task_id") or ""
    status = tracking.get("status") or summary.get("status") or ""
    done = bool(tracking.get("done") or tracking.get("terminal"))
    return {
        "kind": tracking.get("kind") or "long_task",
        "domain": tracking.get("domain") or tracking.get("capability") or "",
        "task_id": task_id,
        "status": status,
        "done": done,
        "terminal": done,
        "mode": policy.get("mode", "") or tracking.get("mode", ""),
        "poll_count": int(tracking.get("poll_count") or 0),
        "same_status_count": int(tracking.get("same_status_count") or 0),
        "stall_risk": bool(tracking.get("stall_risk")),
        "next_poll_seconds": int(tracking.get("next_poll_seconds") or 0),
        "suggested_next_action": tracking.get("suggested_next_action", ""),
        "progress": progress,
        "summary": summary,
        "raw": tracking,
    }
