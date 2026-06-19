# agent/runtime/actions/result.py
"""ResultNormalizer — converts raw tool output to normalized ActionResult fields.

Also provides ``action_result_to_tool_result`` for backward-compatible
conversion of ActionResult → ToolResult.
"""

from __future__ import annotations

import json
from typing import Any

from agent.runtime.actions.models import ActionResult


class ResultNormalizer:
    """Normalize raw tool dispatch result into ActionResult fields."""

    def normalize(self, action_result: ActionResult) -> ActionResult:
        """Populate normalized_result from the raw result."""
        raw = action_result.result

        if raw is None:
            action_result.normalized_result = {"ok": action_result.ok, "data": None}
            return action_result

        # If it's already a ToolResult-like object
        if hasattr(raw, "ok") and hasattr(raw, "summary"):
            action_result.ok = raw.ok
            action_result.normalized_result = {
                "ok": raw.ok,
                "summary": getattr(raw, "summary", ""),
                "data": getattr(raw, "data", None),
                "artifacts": getattr(raw, "artifacts", []),
            }
            return action_result

        # Dict result
        if isinstance(raw, dict):
            action_result.normalized_result = raw
            if "ok" in raw:
                action_result.ok = bool(raw["ok"])
            return action_result

        # String result
        if isinstance(raw, str):
            action_result.normalized_result = {"ok": True, "data": raw}
            action_result.ok = True
            return action_result

        # List result
        if isinstance(raw, list):
            action_result.normalized_result = {"ok": True, "data": raw, "count": len(raw)}
            action_result.ok = True
            return action_result

        # Fallback
        action_result.normalized_result = {"ok": action_result.ok, "data": str(raw)[:2000]}
        return action_result


def action_result_to_tool_result(action_result: ActionResult):
    """Convert an ActionResult to a ToolResult for pipeline backward compatibility.

    If the ActionResult already wraps a ToolResult (via .result), that object is
    returned directly.  Otherwise a new ToolResult is synthesised from the
    ActionResult's normalised fields.
    """
    from agent.protocol.tool_result import ToolResult

    raw = action_result.result
    # If raw is already a ToolResult, return it directly
    if isinstance(raw, ToolResult):
        return raw

    # Build summary
    summary = ""
    if action_result.error:
        summary = action_result.error[:200]
    elif isinstance(action_result.normalized_result, dict):
        summary = action_result.normalized_result.get("summary", "")
        if not summary:
            data = action_result.normalized_result.get("data")
            if isinstance(data, str):
                summary = data[:200]
    if not summary and hasattr(raw, "summary"):
        summary = getattr(raw, "summary", "")[:200]
    if not summary:
        summary = f"{action_result.tool_id}: {action_result.status}"

    errors = []
    if action_result.error:
        errors.append(action_result.error[:200])

    return ToolResult(
        ok=action_result.ok,
        summary=summary,
        errors=errors,
        metadata={
            "action_id": action_result.action_id,
            "scan_status": action_result.scan_status,
            "latency_ms": action_result.latency_ms,
        },
    )
