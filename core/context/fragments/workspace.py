# context/fragments/workspace.py
"""Workspace state fragment — session identity + last result context."""

from __future__ import annotations

import logging
from .base import ContextFragment, FragmentPriority

logger = logging.getLogger(__name__)


class WorkspaceStateFragment(ContextFragment):
    """Loads workspace state and last_result context from workspace manager."""

    priority = FragmentPriority.ENVIRONMENT
    token_budget = 4096

    def build(self, state) -> dict:
        ws_id = getattr(state, "workspace_id", "") or ""
        if not ws_id:
            return {"ok": False, "error": "workspace_id_required",
                    "workspace_id": "", "workspace_state_available": False,
                    "last_result": {"has_result": False}}
        context_ref = getattr(state, "context", {}).get("context_ref", "")
        try:
            from workspace.manager import get_workspace_state
            ws = get_workspace_state(ws_id)

            last_result = {"has_result": False}
            if context_ref == "last_result":
                summary = ws.get("last_result_summary", "")
                counts = ws.get("last_result_counts", {})
                samples_mr = ws.get("last_manual_review_samples", [])
                samples_us = ws.get("last_unsupported_samples", [])
                last_result = {
                    "has_result": bool(ws.get("last_intent")),
                    "last_intent": ws.get("last_intent"),
                    "summary": str(summary)[:200],
                    "counts": counts,
                    "manual_review_samples": samples_mr[:5],
                    "unsupported_samples": samples_us[:5],
                    "llm_metadata": ws.get("llm_metadata", {}),
                }

            return {
                "ok": True,
                "workspace_id": ws_id,
                "last_result": last_result,
                "workspace_state_available": True,
            }
        except Exception:
            logger.debug("WorkspaceStateFragment: load failed", exc_info=True)
            return {"ok": True, "workspace_id": ws_id, "workspace_state_available": False,
                    "last_result": {"has_result": False}}

    def render(self, data: dict) -> str:
        if not data.get("workspace_state_available"):
            return ""
        lr = data.get("last_result", {})
        if lr.get("has_result"):
            return self.cap(
                f"[workspace] session={data['workspace_id']} | "
                f"last_intent={lr.get('last_intent', 'none')} | "
                f"summary={lr.get('summary', '')[:100]}"
            )
        return self.cap(f"[workspace] session={data['workspace_id']}")
