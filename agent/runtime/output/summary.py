# agent/runtime/output/summary.py
"""OutputSummarizer — produces an OutputSummary from collected sources and artifact records."""

from __future__ import annotations

from agent.runtime.output.models import ArtifactRecord, OutputSource, OutputSummary


class OutputSummarizer:
    """Build a single OutputSummary for the current step/task."""

    def summarize(
        self,
        ctx,
        sources: list[OutputSource],
        records: list[ArtifactRecord],
        *,
        task_id: str = "",
        step_id: str = "",
    ) -> OutputSummary:
        warnings: list[str] = []
        failed = [r for r in records if r.status == "failed"]
        if failed:
            warnings.append(f"{len(failed)} artifact(s) failed to write")

        artifact_ids = [r.artifact_id for r in records]
        source_ids = [s.source_id for s in sources]
        summary_parts = []
        for r in records:
            if r.status in ("created", "registered"):
                summary_parts.append(f"[{r.kind}] {r.title}")

        out = OutputSummary(
            task_id=task_id,
            step_id=step_id,
            artifact_ids=artifact_ids,
            source_ids=source_ids,
            summary="; ".join(summary_parts)[:1000] or "no artifacts produced",
            warnings=warnings,
        )

        ctx.metadata["output_summary"] = {
            "task_id": out.task_id,
            "step_id": out.step_id,
            "artifact_ids": out.artifact_ids,
            "source_ids": out.source_ids,
            "summary": out.summary,
            "warnings": out.warnings,
        }
        return out
