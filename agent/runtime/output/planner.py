# agent/runtime/output/planner.py
"""ArtifactPlanner — generates ArtifactPlan from collected OutputSources."""

from __future__ import annotations

import uuid

from agent.runtime.output.models import ArtifactPlan, OutputSource


_CONTENT_TYPE_TO_KIND = {
    "text": "markdown",
    "json": "json",
    "table": "csv",
    "log": "log",
    "file": "other",
    "image": "image",
    "unknown": "other",
}


class ArtifactPlanner:
    """Decide which sources should become artifacts and plan their creation."""

    def plan(self, sources: list[OutputSource], *, task_id: str = "", step_id: str = "") -> list[ArtifactPlan]:
        plans: list[ArtifactPlan] = []
        for src in sources:
            if not src.content:
                continue
            kind = _CONTENT_TYPE_TO_KIND.get(src.content_type, "other")
            ext = _kind_to_ext(kind)
            aid = f"art_{uuid.uuid4().hex[:8]}"
            plan = ArtifactPlan(
                artifact_id=aid,
                task_id=task_id or src.task_id,
                step_id=step_id or src.step_id,
                source_ids=[src.source_id],
                kind=kind,
                title=src.summary[:80] or f"{src.tool_id or 'output'}_{aid[:12]}",
                filename=f"{aid}.{ext}",
                target_path=f"workspace/output/artifacts/{aid}.{ext}",
                write_mode="register_only",
            )
            plans.append(plan)
        return plans


def _kind_to_ext(kind: str) -> str:
    return {
        "markdown": "md",
        "txt": "txt",
        "json": "json",
        "csv": "csv",
        "log": "log",
        "table": "csv",
        "image": "png",
        "other": "txt",
    }.get(kind, "txt")
