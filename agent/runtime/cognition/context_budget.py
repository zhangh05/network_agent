# agent/runtime/cognition/context_budget.py
"""ContextBudgetManager — EvidenceItem-level budget compaction.

Works directly on EvidenceBundle items with layered compression.
"""

from __future__ import annotations

import json
from typing import Any

from agent.runtime.cognition.evidence_models import BudgetReport, EvidenceBundle


def _is_cjk(c: str) -> bool:
    cp = ord(c)
    return (
        0x4E00 <= cp <= 0x9FFF or    # CJK Unified Ideographs
        0x3400 <= cp <= 0x4DBF or    # CJK Extension A
        0x3000 <= cp <= 0x303F or    # CJK Symbols and Punctuation
        0x31C0 <= cp <= 0x31EF or    # CJK Strokes
        0x3200 <= cp <= 0x32FF or    # Enclosed CJK Letters
        0x3300 <= cp <= 0x33FF or    # CJK Compatibility
        0xFE30 <= cp <= 0xFE4F or    # CJK Compatibility Forms
        0xFF00 <= cp <= 0xFFEF       # Halfwidth and Fullwidth Forms
    )


def _estimate_text_tokens(text: str) -> int:
    """CJK-aware token estimation: CJK ~1 char/token, ASCII ~4 chars/token."""
    if not text:
        return 0
    s = str(text)
    cjk = sum(1 for c in s if _is_cjk(c))
    non_cjk = len(s) - cjk
    return max(1, cjk + non_cjk // 4)


class ContextBudgetManager:
    """Apply token budget constraints, working at EvidenceItem level."""

    def __init__(self):
        self.last_report: BudgetReport = BudgetReport()

    def apply(self, evidence: EvidenceBundle, ctx, bundle=None) -> EvidenceBundle:
        """Apply budget compaction directly on EvidenceBundle items."""
        estimated = self._estimate_tokens(evidence)
        budget = self._resolve_budget(ctx)
        threshold = int(budget * 0.85)

        ctx.metadata.setdefault("context_budget", {
            "estimated_tokens": estimated,
            "budget_tokens": budget,
            "threshold_tokens": threshold,
        })

        if estimated <= threshold:
            evidence.budget_report = BudgetReport(
                estimated_tokens=estimated,
                budget_tokens=budget,
                threshold_tokens=threshold,
                compacted=False,
            )
            self.last_report = evidence.budget_report
            return evidence

        # ── Compaction layers ──────────────────────────────────────
        ctx.metadata["auto_compact"] = True
        ctx.metadata["compact_pre_tokens"] = estimated
        decisions: list[dict[str, Any]] = ctx.metadata.setdefault("compact_decisions", [])

        # Layer 1: trim history
        if hasattr(ctx, "history_window") and len(ctx.history_window) > 2:
            before = len(ctx.history_window)
            keep = max(2, len(ctx.history_window) - 2)
            ctx.history_window = ctx.history_window[-keep:]
            after = len(ctx.history_window)
            decisions.append({"layer": "trim_history", "before": before, "after": after})
            ctx.metadata["compact_layer"] = "trim_history"
            ctx.metadata["compact_history_before"] = before
            ctx.metadata["compact_history_after"] = after
            post = self._estimate_tokens(evidence) + self._estimate_history_tokens(ctx)
            if post <= threshold:
                ctx.metadata["compact_post_tokens"] = post
                evidence.budget_report = BudgetReport(
                    estimated_tokens=post, budget_tokens=budget,
                    threshold_tokens=threshold, compacted=True, decisions=list(decisions),
                )
                self.last_report = evidence.budget_report
                return evidence

        # Layer 2: drop low-score knowledge items (keep top 3 non-blocked)
        non_blocked_k = [i for i in evidence.knowledge_items if i.scan_status != "blocked"]
        blocked_k = [i for i in evidence.knowledge_items if i.scan_status == "blocked"]
        if len(non_blocked_k) > 1:
            before_count = len(non_blocked_k)
            scored = sorted(non_blocked_k, key=lambda i: i.score, reverse=True)
            keep_count = max(1, min(3, len(scored)))
            evidence.knowledge_items = scored[:keep_count] + blocked_k
            decisions.append({"layer": "drop_low_score", "before": before_count, "after": keep_count})
            ctx.metadata["compact_layer"] = "drop_low_score"
            ctx.metadata["compact_knowledge_before"] = before_count
            ctx.metadata["compact_knowledge_after"] = keep_count
            post = self._estimate_tokens(evidence)
            if post <= threshold:
                ctx.metadata["compact_post_tokens"] = post
                evidence.budget_report = BudgetReport(
                    estimated_tokens=post, budget_tokens=budget,
                    threshold_tokens=threshold, compacted=True, decisions=list(decisions),
                )
                self.last_report = evidence.budget_report
                return evidence

        # Layer 3: summarize memory items (non-blocked only)
        non_blocked_m = [i for i in evidence.memory_items if i.scan_status != "blocked"]
        blocked_m = [i for i in evidence.memory_items if i.scan_status == "blocked"]
        if len(non_blocked_m) > 1:
            before_count = len(non_blocked_m)
            summaries = []
            for item in non_blocked_m:
                title = item.title or item.summary or ""
                if title:
                    summaries.append(title[:80])
            if summaries:
                from agent.runtime.cognition.evidence_models import EvidenceItem
                evidence.memory_items = [EvidenceItem(
                    source_type="memory",
                    title="",
                    summary=" | ".join(summaries)[:500],
                    scan_status="safe",
                )] + blocked_m
                decisions.append({"layer": "summarize_memory", "before": before_count, "after": 1})
                ctx.metadata["compact_layer"] = "summarize_memory"
                ctx.metadata["compact_memory_before"] = before_count
                post = self._estimate_tokens(evidence)
                if post <= threshold:
                    ctx.metadata["compact_post_tokens"] = post
                    evidence.budget_report = BudgetReport(
                        estimated_tokens=post, budget_tokens=budget,
                        threshold_tokens=threshold, compacted=True, decisions=list(decisions),
                    )
                    self.last_report = evidence.budget_report
                    return evidence

        # Layer 4: drop extras (workspace_state, citations, context_sources)
        dropped = []
        if evidence.workspace_state:
            dropped.append("workspace_state")
            evidence.workspace_state = {}
        if evidence.citations:
            dropped.append("citations")
            evidence.citations = []
        if evidence.context_sources:
            dropped.append("context_sources")
            evidence.context_sources = []
        decisions.append({"layer": "drop_extras", "dropped": dropped})
        ctx.metadata["compact_layer"] = "drop_extras"
        ctx.metadata["compact_post_tokens"] = self._estimate_tokens(evidence)

        evidence.budget_report = BudgetReport(
            estimated_tokens=ctx.metadata["compact_post_tokens"],
            budget_tokens=budget,
            threshold_tokens=threshold,
            compacted=True,
            decisions=list(decisions),
        )
        self.last_report = evidence.budget_report
        return evidence

    # ── Private helpers ────────────────────────────────────────────

    @staticmethod
    def _estimate_tokens(evidence: EvidenceBundle) -> int:
        """Rough token estimation from the EvidenceBundle's safe_context form."""
        try:
            text = json.dumps(evidence.to_safe_context(), ensure_ascii=False)
            return _estimate_text_tokens(text)
        except Exception:
            return _estimate_text_tokens(str(evidence))

    @staticmethod
    def _estimate_history_tokens(ctx) -> int:
        try:
            total = 0
            for h in getattr(ctx, "history_window", []):
                if hasattr(h, "content"):
                    total += _estimate_text_tokens(str(h.content))
                elif isinstance(h, dict):
                    total += _estimate_text_tokens(json.dumps(h, ensure_ascii=False))
            return total
        except Exception:
            return 0

    @staticmethod
    def _resolve_budget(ctx) -> int:
        try:
            model = ctx.model_config.get("model", "") if ctx.model_config else ""
            from core.context.schemas import resolve_budget_for_model
            b = resolve_budget_for_model(model)
            return b.max_chars // 4 if b.max_chars else 3000
        except Exception:
            return 3000
