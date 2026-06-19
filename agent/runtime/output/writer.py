# agent/runtime/output/writer.py
"""ArtifactWriter — safe artifact writer (markdown/txt/json/csv only)."""

from __future__ import annotations

import json
import os
from typing import Any

from agent.runtime.output.models import ArtifactPlan, ArtifactRecord, OutputSource


_SAFE_KINDS = {"markdown", "txt", "json", "csv", "log"}


class ArtifactWriter:
    """Write artifact files for safe formats. Others are register_only."""

    def write(self, plan: ArtifactPlan, sources: list[OutputSource]) -> ArtifactRecord:
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
            target_dir = os.path.dirname(plan.target_path)
            if target_dir and not os.path.exists(target_dir):
                os.makedirs(target_dir, exist_ok=True)
            with open(plan.target_path, "w", encoding="utf-8") as fh:
                fh.write(content)
            record.status = "created"
            record.summary = f"Written {plan.kind} to {plan.target_path}"
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
