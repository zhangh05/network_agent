# agent/runtime/cognition/context_budget.py
"""ContextBudgetManager — wraps auto_compact_context for EvidenceItem-level decisions."""

from __future__ import annotations

from agent.runtime.cognition.evidence_models import BudgetReport


class ContextBudgetManager:
    """Apply token budget constraints, working at EvidenceItem level."""

    def apply(self, safe_context: dict, ctx, bundle=None) -> dict:
        """Apply budget compaction. Delegates to existing auto_compact_context."""
        from agent.runtime.context_compaction import auto_compact_context
        compacted = auto_compact_context(safe_context, ctx, bundle)

        budget_meta = ctx.metadata.get("context_budget", {})
        self.last_report = BudgetReport(
            estimated_tokens=budget_meta.get("estimated_tokens", 0),
            budget_tokens=budget_meta.get("budget_tokens", 0),
            threshold_tokens=budget_meta.get("threshold_tokens", 0),
            compacted=ctx.metadata.get("auto_compact", False),
            decisions=ctx.metadata.get("compact_decisions", []),
        )
        return compacted
