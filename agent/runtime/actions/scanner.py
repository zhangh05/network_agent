# agent/runtime/actions/scanner.py
"""ResultScanner — scans ActionResult content for prompt injection."""

from __future__ import annotations

import json
from typing import Any

from agent.runtime.actions.models import ActionResult


def _extract_text_content(result: ActionResult) -> str:
    """Extract text content from the result for scanning."""
    parts = []
    raw = result.result

    # From normalized_result
    if isinstance(result.normalized_result, dict):
        for key in ("summary", "data", "content", "text", "output", "stdout"):
            val = result.normalized_result.get(key)
            if isinstance(val, str):
                parts.append(val)

    # From raw ToolResult-like object
    if hasattr(raw, "summary") and isinstance(raw.summary, str):
        parts.append(raw.summary)
    if hasattr(raw, "content") and isinstance(raw.content, str):
        parts.append(raw.content)

    # If raw is a string
    if isinstance(raw, str):
        parts.append(raw)

    return "\n".join(parts)[:50000]


class ResultScanner:
    """Scan action results for prompt injection patterns."""

    def scan(self, action_result: ActionResult) -> ActionResult:
        """Scan the result content and set scan_status."""
        content = _extract_text_content(action_result)
        if not content:
            action_result.scan_status = "safe"
            return action_result

        try:
            from agent.runtime.rag_injection_scan import scan_chunk
            scan_result = scan_chunk(
                content=content,
                chunk_id=action_result.action_id,
                source="tool_output",
            )
            risk = getattr(scan_result, "risk_level", "low") if scan_result else "low"
            if risk == "high":
                action_result.scan_status = "blocked"
                action_result.metadata["injection_scan"] = "high_risk_blocked"
            elif risk == "medium":
                action_result.scan_status = "summary"
                action_result.metadata["injection_scan"] = "medium_risk_summary"
            else:
                action_result.scan_status = "safe"
        except ImportError:
            action_result.scan_status = "skipped"
        except Exception:
            action_result.scan_status = "skipped"

        return action_result
