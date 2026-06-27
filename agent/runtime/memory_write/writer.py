# agent/runtime/memory_write/writer.py
"""MemoryWriter — persists memory candidates to the real ContextStore.

Replaces the stub writer with actual persistence via memory/store.py:get_store().put().
"""

from __future__ import annotations

import logging

from agent.runtime.memory_write.models import MemoryWritePlan

_log = logging.getLogger("memory_write.writer")

# Hard cap — never write more than this per turn, regardless of LLM gate output
MAX_WRITE_PER_TURN = 3


class MemoryWriter:
    """Write memory candidates to persistent storage.

    Delegates to memory/store.py (ContextStoreAdapter) for actual I/O.
    Handles rate-limiting and error isolation so a single bad write
    never blocks the turn pipeline.
    """

    def write(self, ctx, plan: MemoryWritePlan, workspace_id: str = "") -> dict:
        """Persist accepted candidates to ContextStore.

        Args:
            ctx: TurnContext (for workspace_id fallback)
            plan: MemoryWritePlan with candidates to write
            workspace_id: Target workspace (defaults to ctx.workspace_id)

        Returns:
            dict with status, written_ids, skipped count, and any errors
        """
        if not plan.candidates:
            return {"status": "empty", "written_count": 0, "written_ids": [], "errors": []}

        ws_id = workspace_id or getattr(ctx, "workspace_id", "") or ""
        if not ws_id:
            return {"status": "error", "written_count": 0, "written_ids": [],
                    "errors": ["workspace_id is required"]}

        from workspace.memory_governance import MemoryRecord, MemoryWriteGate

        gate = MemoryWriteGate()
        written_ids: list[str] = []
        errors: list[str] = []
        # Apply per-turn cap — take highest-confidence candidates first
        sorted_candidates = sorted(plan.candidates, key=lambda c: c.confidence, reverse=True)

        for c in sorted_candidates[:MAX_WRITE_PER_TURN]:
            try:
                rec = MemoryRecord(
                    workspace_id=ws_id,
                    session_id=getattr(ctx, "session_id", ""),
                    task_id=c.task_id,
                    scope="workspace",
                    memory_type=c.memory_type,
                    status="active" if c.confidence >= 0.8 else "pending",
                    source="agent_suggestion",
                    content=c.content[:2000],
                    summary=c.metadata.get("summary", c.content[:200]),
                    confidence=c.confidence,
                    citations=[],
                    created_by="agent_suggestion",
                    redacted=True,
                )
                result = gate.write(rec)
                if result.get("ok"):
                    written_ids.append(result.get("memory_id", c.candidate_id))
                else:
                    errors.append(f"gate_rejected: {c.candidate_id}: {result.get('error', 'unknown')}")
                _log.debug("Memory gate write %s (type=%s, confidence=%.2f)", c.candidate_id, c.memory_type, c.confidence)
            except Exception as e:
                _log.exception("Failed to write memory candidate %s", c.candidate_id)
                errors.append(f"write_failed: {c.candidate_id}: {e}")

        return {
            "status": "ok" if not errors else "partial",
            "written_count": len(written_ids),
            "written_ids": written_ids,
            "capped_from": len(plan.candidates),
            "errors": errors,
        }
