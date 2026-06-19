# agent/runtime/actions/evidence_update.py
"""EvidenceUpdate — converts successful ActionResult to evidence summary entries."""

from __future__ import annotations

from typing import Any

from agent.runtime.actions.models import ActionPlan, ActionResult


class EvidenceUpdate:
    """Convert successful action results to evidence summary entries."""

    def update(self, plan: ActionPlan, result: ActionResult) -> list:
        """Generate evidence update entries from a successful result.

        Returns a list of evidence dicts for context enrichment.
        """
        if not result.ok:
            return []

        entries = []

        summary = ""
        if result.normalized_result and isinstance(result.normalized_result, dict):
            summary = result.normalized_result.get("summary", "")
            if not summary:
                data = result.normalized_result.get("data")
                if isinstance(data, str):
                    summary = data[:300]
                elif isinstance(data, dict):
                    summary = str(data)[:300]
                elif isinstance(data, list):
                    summary = f"{len(data)} items returned"

        if not summary and hasattr(result.result, "summary"):
            summary = getattr(result.result, "summary", "")[:300]

        if summary:
            entries.append({
                "action_id": result.action_id,
                "tool_id": result.tool_id,
                "action_class": plan.action_class,
                "summary": summary[:500],
                "ok": result.ok,
            })

        result.evidence_updates = entries
        return entries
