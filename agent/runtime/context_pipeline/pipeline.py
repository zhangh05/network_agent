# agent/runtime/context_pipeline/pipeline.py
"""ContextPipeline — orchestrates 13 stages to build TurnContext.

Each stage returns ContextStageResult. Failures are recorded
but do NOT abort — the pipeline continues in degraded mode.

The final TurnContext is returned with context_status="ok" or "degraded".
"""

from __future__ import annotations

from agent.runtime.context_pipeline.models import (
    ContextStageResult,
    ContextPipelineMeta,
    StageName,
)
from agent.runtime.context_pipeline.stages import (
    ContextInitStage,
    ModelConfigStage,
    HistoryStage,
    ToolRouterStage,
    SkillSelectionStage,
    SceneDecisionStage,
    RetrievalPolicyStage,
    RuntimeStateStage,
    EvidenceStage,
    ToolPlanningStage,
    SafeContextStage,
    LoadedSkillStage,
    MetadataWriteStage,
)


class ContextPipeline:
    """Build TurnContext via 13-stage pipeline.

    Usage:
        pipeline = ContextPipeline()
        ctx = pipeline.run(session, turn, services)
    """

    def __init__(self):
        self._init = ContextInitStage()
        self._model_config = ModelConfigStage()
        self._history = HistoryStage()
        self._tool_router = ToolRouterStage()
        self._skill = SkillSelectionStage()
        self._scene = SceneDecisionStage()
        self._retrieval = RetrievalPolicyStage()
        self._runtime = RuntimeStateStage()
        self._evidence = EvidenceStage()
        self._tool_planning = ToolPlanningStage()
        self._safe_context = SafeContextStage()
        self._loaded_skill = LoadedSkillStage()
        self._metadata_write = MetadataWriteStage()

    def run(self, session, turn, services):
        """Execute all 13 stages in order.

        Returns:
            TurnContext with all metadata populated.
            ctx.metadata["context_status"] == "ok" or "degraded".
            ctx.metadata["context_pipeline_meta"] has aggregate stage results.
        """
        meta = ContextPipelineMeta()
        stage_results: list[ContextStageResult] = []

        # ── Stage 1: Context Init ───────────────────────────────────
        sr = self._init.run(session=session, turn=turn)
        stage_results.append(sr)
        _record_stage(meta, sr)
        if not sr.data.get("ctx"):
            # Fatal: no context object to work with
            from agent.core.turn_context import TurnContext
            ctx = TurnContext(turn_id="", session_id="", workspace_id="default", trace_id="", user_input="")
            ctx.metadata["context_status"] = "degraded"
            ctx.metadata["context_pipeline_meta"] = meta.to_dict()
            ctx.metadata["context_pipeline_results"] = [r.to_dict() for r in stage_results]
            return ctx
        ctx = sr.data["ctx"]

        # ── Stage 2: Model Config ───────────────────────────────────
        sr = self._model_config.run(ctx=ctx)
        stage_results.append(sr)
        _record_stage(meta, sr)

        # ── Stage 3: History ────────────────────────────────────────
        sr = self._history.run(ctx=ctx, session=session)
        stage_results.append(sr)
        _record_stage(meta, sr)

        # ── Stage 4: Tool Router ────────────────────────────────────
        sr = self._tool_router.run(ctx=ctx, services=services)
        stage_results.append(sr)
        _record_stage(meta, sr)

        # ── Stage 5: Skill Selection ────────────────────────────────
        sr = self._skill.run(ctx=ctx, services=services)
        stage_results.append(sr)
        _record_stage(meta, sr)
        selected_skills = sr.data.get("selected_skills", [])
        skill_snapshot = sr.data.get("skill_snapshot", {})
        module_snapshot = sr.data.get("module_snapshot", {})
        capability_registry = sr.data.get("capability_registry")

        # ── Stage 6: Scene Decision ─────────────────────────────────
        sr = self._scene.run(ctx=ctx, session=session)
        stage_results.append(sr)
        _record_stage(meta, sr)

        # ── Stage 7: Retrieval Policy (P1-B) ────────────────────────
        sr = self._retrieval.run(ctx=ctx, session=session)
        stage_results.append(sr)
        _record_stage(meta, sr)

        # ── Stage 8: Runtime State ──────────────────────────────────
        sr = self._runtime.run(ctx=ctx, session=session)
        stage_results.append(sr)
        _record_stage(meta, sr)

        # ── Stage 9: Evidence Pipeline ──────────────────────────────
        sr = self._evidence.run(ctx=ctx, turn=turn, selected_skills=selected_skills, services=services)
        stage_results.append(sr)
        _record_stage(meta, sr)
        evidence_bundle = sr.data.get("evidence_bundle")

        # ── Stage 10: Tool Planning ─────────────────────────────────
        sr = self._tool_planning.run(
            ctx=ctx, evidence_bundle=evidence_bundle,
            session=session, services=services, selected_skills=selected_skills,
        )
        stage_results.append(sr)
        _record_stage(meta, sr)
        selected_visible_tools = sr.data.get("selected_visible_tools", [])
        tool_scene = sr.data.get("tool_scene", {})
        rule_tool_scene = sr.data.get("rule_tool_scene", {})

        # ── Stage 11: Safe Context ──────────────────────────────────
        sr = self._safe_context.run(
            ctx=ctx, evidence_bundle=evidence_bundle, services=services,
            tool_scene=tool_scene, rule_tool_scene=rule_tool_scene,
            selected_visible_tools=selected_visible_tools,
            selected_skills=selected_skills,
            skill_snapshot=skill_snapshot, module_snapshot=module_snapshot,
            capability_registry=capability_registry,
        )
        stage_results.append(sr)
        _record_stage(meta, sr)

        # ── Stage 12: Loaded Skills ─────────────────────────────────
        sr = self._loaded_skill.run(ctx=ctx, session=session)
        stage_results.append(sr)
        _record_stage(meta, sr)

        # ── Stage 13: Metadata Write ────────────────────────────────
        sr = self._metadata_write.run(
            ctx=ctx, session=session,
            selected_skills=selected_skills,
            selected_visible_tools=selected_visible_tools,
            tool_scene=tool_scene, rule_tool_scene=rule_tool_scene,
        )
        stage_results.append(sr)
        _record_stage(meta, sr)

        # ── Finalize ────────────────────────────────────────────────
        ctx.metadata["context_status"] = meta.status
        ctx.metadata["context_pipeline_meta"] = meta.to_dict()
        ctx.metadata["context_pipeline_results"] = [
            r.to_dict() for r in stage_results
        ]

        return ctx


def _record_stage(meta: ContextPipelineMeta, sr: ContextStageResult) -> None:
    """Record a stage result into the aggregate meta."""
    meta.stages_run += 1
    if sr.ok:
        meta.stages_ok += 1
    else:
        meta.stages_degraded += 1
    meta.warnings.extend(sr.warnings)
    meta.errors.extend(sr.errors)
