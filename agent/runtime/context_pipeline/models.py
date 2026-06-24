# agent/runtime/context_pipeline/models.py
"""Context pipeline models — stage result and pipeline metadata."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class StageName(str, Enum):
    INIT = "context_init"
    MODEL_CONFIG = "model_config"
    HISTORY = "history"
    TOOL_ROUTER = "tool_router"
    CAPABILITY_SELECTION = "capability_selection"
    SCENE_DECISION = "scene_decision"
    RETRIEVAL_POLICY = "retrieval_policy"
    RUNTIME_STATE = "runtime_state"
    EVIDENCE = "evidence"
    TOOL_PLANNING = "tool_planning"
    SAFE_CONTEXT = "safe_context"
    LOADED_CAPABILITY = "loaded_capability"
    METADATA_WRITE = "metadata_write"


@dataclass
class ContextStageResult:
    """Unified output from each pipeline stage.

    Rules:
      - ok=False does NOT abort the pipeline; it records degradation.
      - warnings: non-fatal issues the stage recovered from.
      - errors: things that went wrong (injects context_errors).
      - metadata: stage-specific data that is merged into ctx.metadata.
    """

    name: StageName
    ok: bool = True
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    # ── Carry-over data (used by downstream stages) ──
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name.value,
            "ok": self.ok,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "metadata": {k: _safe_val(v) for k, v in self.metadata.items()},
        }

    @classmethod
    def ok_result(cls, name: StageName, **meta) -> "ContextStageResult":
        return cls(name=name, ok=True, metadata=dict(meta))

    @classmethod
    def degraded(cls, name: StageName, errors: list[str], warnings: list[str] = None) -> "ContextStageResult":
        return cls(name=name, ok=False, errors=list(errors), warnings=list(warnings or []))

    @classmethod
    def failed(cls, name: StageName, error_msg: str) -> "ContextStageResult":
        return cls(name=name, ok=False, errors=[str(error_msg)[:200]])


@dataclass
class ContextPipelineMeta:
    """Aggregate result of running the entire pipeline."""

    stages_run: int = 0
    stages_ok: int = 0
    stages_degraded: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def is_degraded(self) -> bool:
        return self.stages_degraded > 0

    @property
    def status(self) -> str:
        return "degraded" if self.is_degraded else "ok"

    def to_dict(self) -> dict:
        return {
            "stages_run": self.stages_run,
            "stages_ok": self.stages_ok,
            "stages_degraded": self.stages_degraded,
            "status": self.status,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


def _safe_val(v, max_len: int = 500) -> str:
    if isinstance(v, str):
        return v[:max_len]
    return str(v)[:max_len]
