# agent/runtime/actions/result.py
"""ResultNormalizer — converts raw tool output to normalized ActionResult fields."""

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
