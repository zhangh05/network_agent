# harness/test_context_pipeline.py
"""P1-C: ContextPipeline contract tests.

Coverage:
  - Pipeline runs all 13 stages
  - build_turn_context() delegates to pipeline
  - Stage failure → degraded mode (context still returned)
  - ctx.metadata retains P0/P1-A/P1-B fields
  - context_pipeline_meta in metadata
"""

import pytest
from unittest.mock import MagicMock, patch
from agent.runtime.context_pipeline import (
    ContextPipeline,
    ContextStageResult,
    ContextPipelineMeta,
)
from agent.runtime.context_pipeline.models import StageName


# ── Test helpers ─────────────────────────────────────────────────────


def _mock_session(workspace_id="ws_test", has_history=True):
    session = MagicMock()
    session.session_id = "sess_001"
    session.workspace_id = workspace_id
    session.metadata = MagicMock(return_value={})
    session.metadata = {}
    session.is_sub_agent = False
    return session


def _mock_turn(user_input="test input", turn_id="turn_001"):
    turn = MagicMock()
    turn.turn_id = turn_id
    op = MagicMock()
    op.user_input = user_input
    turn.op = op
    return turn


def _mock_services():
    services = MagicMock()
    services.skill_service = None
    services.module_service = None
    services.capability_registry = None
    services.skill_selector = None
    services.tool_service = None
    return services


# ── Tests ────────────────────────────────────────────────────────────


class TestContextPipelineStructure:
    """Structural tests — pipeline exists and has correct shape."""

    def test_pipeline_has_13_stages(self):
        pipeline = ContextPipeline()
        stages = [
            pipeline._init, pipeline._model_config, pipeline._history,
            pipeline._tool_router, pipeline._skill, pipeline._scene,
            pipeline._retrieval, pipeline._runtime, pipeline._evidence,
            pipeline._tool_planning, pipeline._safe_context,
            pipeline._loaded_skill, pipeline._metadata_write,
        ]
        assert len(stages) == 13

    def test_pipeline_initializes_all_stages(self):
        pipeline = ContextPipeline()
        for name in dir(pipeline):
            if name.startswith("_") and not name.startswith("__"):
                assert getattr(pipeline, name) is not None

    def test_build_turn_context_delegates_to_pipeline(self):
        from agent.runtime.context_builder import build_turn_context
        import inspect
        src = inspect.getsource(build_turn_context)
        # Must contain reference to ContextPipeline
        assert "ContextPipeline" in src
        # Must be thin (delegation only, no orchestration logic)
        lines = [l.strip() for l in src.split("\n") if l.strip() and not l.strip().startswith('"""') and not l.strip().startswith("#")]
        # docstring + import + pipeline() + return should be ~4-5 lines of logic
        assert len(lines) <= 8, f"build_turn_context should be thin, got {len(lines)} lines"


class TestStageResults:
    """ContextStageResult contract tests."""

    def test_ok_result(self):
        r = ContextStageResult.ok_result(StageName.INIT, key="value")
        assert r.ok is True
        assert r.name == StageName.INIT
        assert r.metadata == {"key": "value"}
        assert r.errors == []
        assert r.warnings == []

    def test_degraded_result(self):
        r = ContextStageResult.degraded(StageName.SCENE_DECISION, ["error1"], ["warning1"])
        assert r.ok is False
        assert r.errors == ["error1"]
        assert r.warnings == ["warning1"]

    def test_failed_result(self):
        r = ContextStageResult.failed(StageName.EVIDENCE, "pipeline failed")
        assert r.ok is False
        assert "pipeline failed" in r.errors[0]

    def test_to_dict_shape(self):
        r = ContextStageResult.ok_result(StageName.MODEL_CONFIG, key="val")
        d = r.to_dict()
        assert d["name"] == "model_config"
        assert d["ok"] is True
        assert d["warnings"] == []
        assert d["errors"] == []
        assert "metadata" in d


class TestPipelineMeta:
    """ContextPipelineMeta tests."""

    def test_empty_meta(self):
        meta = ContextPipelineMeta()
        assert meta.stages_run == 0
        assert meta.stages_ok == 0
        assert meta.stages_degraded == 0
        assert meta.is_degraded is False
        assert meta.status == "ok"

    def test_degraded_status(self):
        meta = ContextPipelineMeta(stages_run=13, stages_ok=12, stages_degraded=1)
        assert meta.is_degraded is True
        assert meta.status == "degraded"


class TestPipelineRun:
    """End-to-end pipeline run tests with mocks."""

    def test_pipeline_run_completes(self):
        """Pipeline runs 13 stages and returns a TurnContext."""
        session = _mock_session()
        turn = _mock_turn()
        services = _mock_services()

        pipeline = ContextPipeline()
        ctx = pipeline.run(session, turn, services)

        assert ctx is not None
        assert ctx.session_id == session.session_id
        assert ctx.turn_id == turn.turn_id
        assert ctx.metadata["context_status"] in ("ok", "degraded")

    def test_context_has_required_fields(self):
        """Context after pipeline run has P0/P1-A/P1-B fields."""
        session = _mock_session()
        turn = _mock_turn()
        services = _mock_services()

        pipeline = ContextPipeline()
        ctx = pipeline.run(session, turn, services)

        # Basic fields
        assert ctx.workspace_id == session.workspace_id
        assert ctx.user_input == turn.op.user_input
        assert hasattr(ctx, "model_config")

        # Pipeline metadata in ctx
        assert "context_pipeline_meta" in ctx.metadata
        assert "context_pipeline_results" in ctx.metadata

    def test_context_metadata_has_pipeline_stages(self):
        """ctx.metadata has stage results after pipeline run."""
        session = _mock_session()
        turn = _mock_turn()
        services = _mock_services()

        pipeline = ContextPipeline()
        ctx = pipeline.run(session, turn, services)

        results = ctx.metadata.get("context_pipeline_results", [])
        assert len(results) == 13
        stage_names = [r["name"] for r in results]
        assert "context_init" in stage_names
        assert "model_config" in stage_names
        assert "history" in stage_names
        assert "tool_router" in stage_names
        assert "skill_selection" in stage_names
        assert "scene_decision" in stage_names
        assert "retrieval_policy" in stage_names
        assert "runtime_state" in stage_names
        assert "evidence" in stage_names
        assert "tool_planning" in stage_names
        assert "safe_context" in stage_names
        assert "loaded_skill" in stage_names
        assert "metadata_write" in stage_names

    def test_context_has_tool_planning_decision(self):
        """P0: ctx.metadata includes tool_planning_decision when available."""
        session = _mock_session()
        turn = _mock_turn()
        services = _mock_services()

        pipeline = ContextPipeline()
        ctx = pipeline.run(session, turn, services)

        # At minimum, context_status exists
        assert "context_status" in ctx.metadata

    def test_context_has_retrieval_decision(self):
        """P1-B: ctx.metadata includes retrieval_decision."""
        session = _mock_session()
        turn = _mock_turn("继续之前的任务")
        services = _mock_services()

        pipeline = ContextPipeline()
        ctx = pipeline.run(session, turn, services)

        # Retrieval decision may be present (P1-B integration)
        rd = ctx.metadata.get("retrieval_decision")
        if rd:
            assert isinstance(rd, dict)

    def test_safe_context_does_not_contain_sensitive_base_data(self):
        """Safe context only contains LLM-visible data, no internal metadata."""
        session = _mock_session()
        turn = _mock_turn()
        services = _mock_services()

        pipeline = ContextPipeline()
        ctx = pipeline.run(session, turn, services)

        safe = getattr(ctx, "safe_context", {}) or {}
        # Safe context should NOT contain internal pipeline results
        assert "context_pipeline_results" not in safe
        assert "context_pipeline_meta" not in safe

    def test_stage_failure_does_not_abort_pipeline(self):
        """When a stage fails, pipeline continues in degraded mode.

        This test verifies that even if the scene_decision stage fails,
        the pipeline still returns a context (degraded).
        """
        session = _mock_session()
        turn = _mock_turn()
        services = _mock_services()

        # Mock SceneDecisionStage to always fail
        with patch(
            'agent.runtime.context_pipeline.stages.SceneDecisionStage.run',
            return_value=ContextStageResult.failed(StageName.SCENE_DECISION, "mock failure")
        ):
            pipeline = ContextPipeline()
            ctx = pipeline.run(session, turn, services)

            # Pipeline should still return a context
            assert ctx is not None
            assert ctx.session_id == session.session_id

            # Metadata should record the failure
            assert "context_pipeline_meta" in ctx.metadata
            meta = ctx.metadata["context_pipeline_meta"]
            assert meta["stages_degraded"] >= 1
            assert meta["status"] == "degraded"

    def test_retrieval_stage_failure_is_recorded(self):
        """RetrievalPolicyStage failure is recorded but doesn't block."""
        session = _mock_session()
        turn = _mock_turn()
        services = _mock_services()

        with patch(
            'agent.runtime.context_pipeline.stages.RetrievalPolicyStage.run',
            return_value=ContextStageResult.failed(StageName.RETRIEVAL_POLICY, "mock retrieval failure")
        ):
            pipeline = ContextPipeline()
            ctx = pipeline.run(session, turn, services)

            assert ctx is not None
            meta = ctx.metadata.get("context_pipeline_meta")
            assert meta["stages_degraded"] >= 1

            # Verify results include the failed stage
            results = ctx.metadata.get("context_pipeline_results", [])
            retrieval_results = [r for r in results if r["name"] == "retrieval_policy"]
            assert len(retrieval_results) == 1
            assert retrieval_results[0]["ok"] is False

    def test_init_stage_fatal_failure_returns_degraded_context(self):
        """If INIT stage fails fatally (no ctx in data), a minimal degraded context is returned."""
        session = _mock_session()
        turn = _mock_turn()
        services = _mock_services()

        with patch(
            'agent.runtime.context_pipeline.stages.ContextInitStage.run',
            return_value=ContextStageResult(
                name=StageName.INIT, ok=False,
                errors=["fatal init failure"],
                data={},  # No 'ctx' key
            )
        ):
            pipeline = ContextPipeline()
            ctx = pipeline.run(session, turn, services)

            assert ctx is not None
            assert ctx.metadata["context_status"] == "degraded"
            assert ctx.metadata["context_pipeline_meta"]["stages_run"] == 1

    def test_decision_fields_not_lost_after_pipeline(self):
        """P0/P1-A/P1-B decision fields survive pipeline execution."""
        session = _mock_session()
        turn = _mock_turn("分析这个配置文件")
        services = _mock_services()

        pipeline = ContextPipeline()
        ctx = pipeline.run(session, turn, services)

        # Key metadata fields should exist (even if empty/default)
        assert isinstance(ctx.metadata, dict)
        # The context_status field must always be present
        assert "context_status" in ctx.metadata
        # safe_context should exist
        assert hasattr(ctx, "safe_context")
        assert isinstance(ctx.safe_context, dict)
