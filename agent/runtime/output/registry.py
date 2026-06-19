# agent/runtime/output/registry.py
"""ArtifactRegistry — writes artifact records to ctx.metadata and RuntimeState."""

from __future__ import annotations

from agent.runtime.output.models import ArtifactRecord


class ArtifactRegistry:
    """Central registry for artifact records."""

    def register(self, ctx, record: ArtifactRecord) -> None:
        records = ctx.metadata.setdefault("artifact_records", [])
        records.append(self._to_dict(record))
        self._sync_runtime_state(ctx, record)
        self._sync_task_state(ctx, record)

    def register_all(self, ctx, records: list[ArtifactRecord]) -> None:
        for rec in records:
            self.register(ctx, rec)

    def _sync_runtime_state(self, ctx, record: ArtifactRecord) -> None:
        state = getattr(ctx, "runtime_state", None)
        if state is None:
            return
        if not hasattr(state, "artifacts"):
            return
        if state.artifacts is None:
            state.artifacts = []
        from agent.runtime.state.models import ArtifactState
        art_state = ArtifactState(
            artifact_id=record.artifact_id,
            kind=record.kind,
            path=record.path,
            summary=record.title or record.summary,
            status=record.status,
        )
        state.artifacts.append(art_state)

    def _sync_task_state(self, ctx, record: ArtifactRecord) -> None:
        state = getattr(ctx, "runtime_state", None)
        if state is None:
            return
        task = getattr(state, "active_task", None)
        if task is None:
            return
        if hasattr(task, "artifact_ids") and task.artifact_ids is not None:
            if record.artifact_id not in task.artifact_ids:
                task.artifact_ids.append(record.artifact_id)

    @staticmethod
    def _to_dict(record: ArtifactRecord) -> dict:
        return {
            "artifact_id": record.artifact_id,
            "task_id": record.task_id,
            "step_id": record.step_id,
            "kind": record.kind,
            "title": record.title,
            "path": record.path,
            "summary": record.summary,
            "status": record.status,
            "source_ids": list(record.source_ids),
        }
