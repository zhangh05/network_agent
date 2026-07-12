# agent/runtime/output/writer.py
"""ArtifactWriter — safe artifact writer (markdown/txt/json/csv only)."""

from __future__ import annotations

import json
from typing import Any

from agent.runtime.output.models import ArtifactPlan, ArtifactRecord, OutputSource


_SAFE_KINDS = {"markdown", "txt", "json", "csv", "log"}


class ArtifactWriter:
    """Write artifact files for safe formats. Others are register_only."""

    def write(
        self, plan: ArtifactPlan, sources: list[OutputSource], *, workspace_id: str,
    ) -> ArtifactRecord:
        record = ArtifactRecord(
            artifact_id=plan.artifact_id,
            task_id=plan.task_id,
            step_id=plan.step_id,
            kind=plan.kind,
            title=plan.title,
            path=plan.target_path,
            source_ids=list(plan.source_ids),
        )

        if plan.write_mode == "register_only" or plan.kind not in _SAFE_KINDS:
            record.status = "registered"
            record.summary = f"Registered {plan.kind} artifact (no file write)"
            return record

        content = self._merge_content(sources, plan.kind)
        try:
            from artifacts.store import save_artifact
            saved = save_artifact(
                workspace_id=workspace_id,
                content=content,
                artifact_type=plan.kind,
                title=plan.title,
                source="runtime_output",
                metadata={
                    "task_id": plan.task_id,
                    "step_id": plan.step_id,
                    "source_ids": list(plan.source_ids),
                },
            )
            if saved is None:
                raise RuntimeError("artifact store rejected output")
            record.artifact_id = saved.artifact_id
            record.path = saved.relative_path
            record.metadata["file_id"] = saved.file_id
            record.status = "created"
            record.summary = f"Stored {plan.kind} artifact"
        except Exception as exc:
            record.status = "failed"
            record.summary = f"Write failed: {exc!s}"[:200]

        return record

    @staticmethod
    def _merge_content(sources: list[OutputSource], kind: str) -> str:
        parts: list[str] = []
        for src in sources:
            if src.content is None:
                continue
            if isinstance(src.content, (dict, list)):
                parts.append(json.dumps(src.content, ensure_ascii=False, indent=2))
            else:
                parts.append(str(src.content))
        return "\n\n".join(parts)
