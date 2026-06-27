# agent/runtime/memory_write/planner.py
"""MemoryWritePlanner — extracts memory candidates from turn results and persists them.

Pipeline:
  Extract → ConfidenceFloor → Dedupe → RiskFilter → LLM Gate (optional)
  → CountCap → Writer
"""

from __future__ import annotations

import uuid

from agent.runtime.memory_write.dedupe import MemoryDedupe
from agent.runtime.memory_write.filter import MemoryRiskFilter
from agent.runtime.memory_write.count_cap import MemoryCountCap
from agent.runtime.memory_write.gate import (
    get_gate_mode,
    apply_confidence_floor,
    MemoryGateMode,
)
from agent.runtime.memory_write.models import MemoryCandidate, MemoryWritePlan


class MemoryWritePlanner:
    """Generate a MemoryWritePlan from the current turn's ctx.metadata, then persist it."""

    def __init__(self):
        self._filter = MemoryRiskFilter()
        self._dedupe = MemoryDedupe()
        self._count_cap = MemoryCountCap()

    # ── Public API ───────────────────────────────────────────────────────

    def plan(self, ctx, workspace_id: str = "") -> MemoryWritePlan:
        """Extract, dedupe, filter, and persist memory candidates.

        Steps:
          1. Extract candidates from turn metadata (artifacts, tasks, errors)
          2. Apply confidence floor (per gate mode)
          3. Dedupe (type-aware prefix matching)
          4. Risk-filter (sensitive content — hard reject)
          5. LLM Gate (only in llm_first mode; this is the soft gate)
          6. CountCap (per-type hard limit)
          7. Write to ctx.metadata for observability
          8. Persist through MemoryWriteGate via MemoryWriter

        Args:
            ctx: TurnContext with metadata dict
            workspace_id: target workspace (falls back to ctx.workspace_id)

        Returns:
            MemoryWritePlan for downstream consumers
        """
        ws_id = workspace_id or getattr(ctx, "workspace_id", "") or ""
        gate_mode = get_gate_mode(ws_id)

        # 1. Extract
        candidates = self._extract_candidates(ctx)

        # 2. Confidence floor (pre-filter)
        candidates = apply_confidence_floor(candidates, gate_mode)

        # 3. Dedupe
        candidates = self._dedupe.dedupe(candidates)

        # 4. RiskFilter (hard gate — always runs)
        accepted, skipped = self._filter.filter(candidates)

        # 5. LLM Gate (soft gate — only in llm_first mode)
        if gate_mode == MemoryGateMode.LLM_FIRST and accepted:
            try:
                accepted, llm_skipped = self._run_llm_gate(accepted, gate_mode)
                skipped.extend(llm_skipped)
            except Exception:
                # LLM gate failure → fall through, keep rule-only results
                ctx.metadata.setdefault("runtime_state_warnings", []).append(
                    "memory_llm_gate_failed_falling_back_to_rule_only"
                )

        # 6. CountCap (hard cap — always runs)
        accepted = self._count_cap.apply_to_candidates(accepted)

        task_id = ""
        snap = ctx.metadata.get("runtime_state_snapshot") or {}
        if isinstance(snap, dict):
            task_id = snap.get("active_task_id", "")

        plan = MemoryWritePlan(
            task_id=task_id,
            candidates=accepted,
            skipped=skipped,
            metadata={"gate_mode": gate_mode.value},
        )

        # 7. Observability metadata
        self._write_metadata(ctx, plan, gate_mode)

        # 8. Persist to storage
        write_result = self._persist(ctx, plan, ws_id)
        ctx.metadata["memory_write_result"] = write_result

        return plan

    # ── Candidate Extraction ─────────────────────────────────────────────

    def _extract_candidates(self, ctx) -> list[MemoryCandidate]:
        candidates: list[MemoryCandidate] = []
        candidates.extend(self._from_task_completion(ctx))
        candidates.extend(self._from_error_lessons(ctx))
        return candidates

    def _from_task_completion(self, ctx) -> list[MemoryCandidate]:
        out: list[MemoryCandidate] = []
        snap = ctx.metadata.get("runtime_state_snapshot") or {}
        if not isinstance(snap, dict):
            return out
        if snap.get("task_status") != "completed":
            return out
        task_title = snap.get("active_task_title", "") or snap.get("active_task_id", "")
        out.append(MemoryCandidate(
            candidate_id=f"mc_{uuid.uuid4().hex[:8]}",
            memory_type="task_pattern",
            content=f"Task '{task_title}' completed successfully",
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
            err_msg = str(entry.get("error", ""))
            if len(err_msg) < 5:
                continue
            out.append(MemoryCandidate(
                candidate_id=f"mc_{uuid.uuid4().hex[:8]}",
                memory_type="error_lesson",
                content=f"Action {entry.get('action_id', '')} failed: {err_msg[:200]}",
                source="action",
                confidence=0.5,
            ))
        return out

    # ── LLM Gate ─────────────────────────────────────────────────────────

    def _run_llm_gate(
        self,
        candidates: list[MemoryCandidate],
        mode: MemoryGateMode,
    ) -> tuple[list[MemoryCandidate], list[dict]]:
        """Run LLM-based quality gating.

        Delegates to MemoryLLMGate when available. Falls back to keeping
        all candidates if the LLM is unreachable.

        Returns:
            (accepted, skipped) — skipped is a list of dicts with reason
        """
        try:
            from agent.runtime.memory_write.llm_gate import MemoryLLMGate
            return MemoryLLMGate().gate(candidates)
        except ImportError:
            # LLM gate not yet wired — keep all candidates
            return list(candidates), []
        except Exception:
            # LLM unavailable — keep all candidates
            return list(candidates), []

    # ── Metadata & Persistence ───────────────────────────────────────────

    def _write_metadata(self, ctx, plan: MemoryWritePlan, gate_mode: MemoryGateMode) -> None:
        """Write plan summary to ctx.metadata for observability."""
        ctx.metadata["memory_write_plan"] = {
            "task_id": plan.task_id,
            "gate_mode": gate_mode.value,
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

    def _persist(self, ctx, plan: MemoryWritePlan, workspace_id: str) -> dict:
        """Persist accepted candidates via MemoryWriter."""
        try:
            from agent.runtime.memory_write.writer import MemoryWriter
            return MemoryWriter().write(ctx, plan, workspace_id=workspace_id)
        except Exception as e:
            return {"status": "error", "error": str(e), "written_count": 0, "written_ids": []}
