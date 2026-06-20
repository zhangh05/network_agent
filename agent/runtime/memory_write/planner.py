# agent/runtime/memory_write/planner.py
"""MemoryWritePlanner — extracts memory candidates from turn results."""

from __future__ import annotations

import uuid

from agent.runtime.memory_write.dedupe import MemoryDedupe
from agent.runtime.memory_write.filter import MemoryRiskFilter
from agent.runtime.memory_write.models import MemoryCandidate, MemoryWritePlan


class MemoryWritePlanner:
    """Generate a MemoryWritePlan from the current turn's ctx.metadata."""

    def __init__(self):
        self._filter = MemoryRiskFilter()
        self._dedupe = MemoryDedupe()

    def plan(self, ctx) -> MemoryWritePlan:
        candidates = self._extract_candidates(ctx)
        candidates = self._dedupe.dedupe(candidates)
        accepted, skipped = self._filter.filter(candidates)

        task_id = ""
        snap = ctx.metadata.get("runtime_state_snapshot") or {}
        if isinstance(snap, dict):
            task_id = snap.get("active_task_id", "")

        plan = MemoryWritePlan(
            task_id=task_id,
            candidates=accepted,
            skipped=skipped,
        )
        ctx.metadata["memory_write_plan"] = {
            "task_id": plan.task_id,
            "candidate_count": len(plan.candidates),
            "skipped_count": len(plan.skipped),
            "candidates": [
                {
                    "candidate_id": c.candidate_id,
                    "memory_type": c.memory_type,
                    "content": c.content[:200],
                    "source": c.source,
                    "confidence": c.confidence,
                    "risk_level": c.risk_level,
                }
                for c in plan.candidates
            ],
            "skipped": plan.skipped,
        }
        return plan

    def _extract_candidates(self, ctx) -> list[MemoryCandidate]:
        candidates: list[MemoryCandidate] = []
        candidates.extend(self._from_artifact_summary(ctx))
        candidates.extend(self._from_task_completion(ctx))
        candidates.extend(self._from_error_lessons(ctx))
        return candidates

    def _from_artifact_summary(self, ctx) -> list[MemoryCandidate]:
        out: list[MemoryCandidate] = []
        records = ctx.metadata.get("artifact_records") or []
        for rec in records:
            if not isinstance(rec, dict):
                continue
            if rec.get("status") not in ("created", "registered"):
                continue
            out.append(MemoryCandidate(
                candidate_id=f"mc_{uuid.uuid4().hex[:8]}",
                memory_type="artifact_summary",
                content=f"Artifact: {rec.get('title', '')} [{rec.get('kind', '')}] - {rec.get('summary', '')}",
                source="artifact",
                task_id=rec.get("task_id", ""),
                confidence=0.6,
            ))
        return out

    def _from_task_completion(self, ctx) -> list[MemoryCandidate]:
        out: list[MemoryCandidate] = []
        snap = ctx.metadata.get("runtime_state_snapshot") or {}
        if not isinstance(snap, dict):
            return out
        if snap.get("task_status") != "completed":
            return out
        out.append(MemoryCandidate(
            candidate_id=f"mc_{uuid.uuid4().hex[:8]}",
            memory_type="task_pattern",
            content=f"Task {snap.get('active_task_id', '')} completed successfully",
            source="task",
            task_id=snap.get("active_task_id", ""),
            confidence=0.7,
        ))
        return out

    def _from_error_lessons(self, ctx) -> list[MemoryCandidate]:
        out: list[MemoryCandidate] = []
        trace = ctx.metadata.get("action_trace") or []
        for entry in trace:
            if not isinstance(entry, dict):
                continue
            if entry.get("status") != "failed":
                continue
            out.append(MemoryCandidate(
                candidate_id=f"mc_{uuid.uuid4().hex[:8]}",
                memory_type="error_lesson",
                content=f"Action {entry.get('action_id', '')} failed: {str(entry.get('error', ''))[:200]}",
                source="action",
                confidence=0.5,
            ))
        return out
