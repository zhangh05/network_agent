# agent/runtime/context_pipeline/__init__.py
"""Stage-based TurnContext construction.

Splits build_turn_context() into focused context assembly stages.
Each stage returns ContextStageResult with ok/warnings/errors/metadata.
Failures are recorded but do not block the pipeline (degraded mode).
"""

from agent.runtime.context_pipeline.models import ContextStageResult, ContextPipelineMeta
from agent.runtime.context_pipeline.pipeline import ContextPipeline

__all__ = [
    "ContextStageResult",
    "ContextPipelineMeta",
    "ContextPipeline",
]
