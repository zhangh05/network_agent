# harness/test_agent_core_finalization_refactor.py
"""Tests for Agent Core Finalization Refactor — Rounds 8-13.

Covers:
- Output Kernel (ResultCollector, ArtifactPlanner, ArtifactWriter, ArtifactRegistry, OutputSummarizer)
- Response Composer (ResponsePolicy, ResponseComposer, FinalResponse)
- Memory Writer (MemoryWritePlanner, MemoryRiskFilter, MemoryDedupe)
- Observability (ObservabilityCollector, TurnTrace)
- Truth Source (TruthReport, VersionTruth, ConfigTruth, CapabilityTruth)
- Stability Gate (StabilityGate, StabilityChecks)
"""

import os
import sys
import pytest
from dataclasses import dataclass, field
from typing import Any, Optional, List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Minimal ctx stub ──────────────────────────────────────────────────

@dataclass
class _StubCtx:
    turn_id: str = "turn_001"
    session_id: str = "sess_001"
    workspace_id: str = "default"
    user_input: str = ""
    model_config: dict = field(default_factory=lambda: {"provider_type": "minimax", "model": "M3"})
    metadata: dict = field(default_factory=dict)
    tool_router: Any = None
    runtime_state: Any = None
    scene_decision: Any = None
    evidence_bundle: Any = None


def _make_ctx(**overrides):
    ctx = _StubCtx(**{k: v for k, v in overrides.items() if k != "metadata"})
    if "metadata" in overrides:
        ctx.metadata.update(overrides["metadata"])
    return ctx


# ═══════════════════════════════════════════════════════════════════════
# Round 8: Output Kernel
# ═══════════════════════════════════════════════════════════════════════


class TestOutputModelsImport:
    """Test 1: OutputSource / ArtifactPlan / ArtifactRecord / OutputSummary importable."""

    def test_import_all_output_models(self):
        from agent.runtime.output.models import (
            OutputSource,
            ArtifactPlan,
            ArtifactRecord,
            OutputSummary,
        )
        src = OutputSource(source_id="s1", source_type="action_result")
        assert src.source_id == "s1"
        plan = ArtifactPlan(artifact_id="a1", kind="json")
        assert plan.kind == "json"
        rec = ArtifactRecord(artifact_id="a1", status="created")
        assert rec.status == "created"
        out = OutputSummary(task_id="t1")
        assert out.task_id == "t1"


class TestResultCollector:
    """Test 2: ResultCollector generates sources from action_evidence_updates."""

    def test_collect_from_evidence_updates(self):
        from agent.runtime.output.collector import ResultCollector

        ctx = _make_ctx(metadata={
            "action_evidence_updates": [
                {"tool_id": "shell_exec", "summary": "ran ls"},
                {"tool_id": "file_read", "summary": "read config.json"},
            ],
        })
        collector = ResultCollector()
        sources = collector.collect(ctx)
        assert len(sources) == 2
        assert all(s.source_type == "action_result" for s in sources)
        assert sources[0].tool_id == "shell_exec"

    def test_collect_from_action_trace(self):
        from agent.runtime.output.collector import ResultCollector

        ctx = _make_ctx(metadata={
            "action_trace": [
                {"type": "result", "action_id": "act_1", "tool_id": "t1", "result": "ok", "status": "success"},
                {"type": "plan", "action_id": "act_2"},  # not a result
            ],
        })
        collector = ResultCollector()
        sources = collector.collect(ctx)
        assert len(sources) == 1
        assert sources[0].action_id == "act_1"


class TestArtifactPlanner:
    """Test 3: ArtifactPlanner generates plans."""

    def test_plan_from_sources(self):
        from agent.runtime.output.models import OutputSource
        from agent.runtime.output.planner import ArtifactPlanner

        sources = [
            OutputSource(source_id="s1", content_type="text", content="hello world", summary="greeting"),
            OutputSource(source_id="s2", content_type="json", content={"key": "val"}, summary="data"),
        ]
        planner = ArtifactPlanner()
        plans = planner.plan(sources, task_id="t1")
        assert len(plans) == 2
        assert plans[0].kind == "markdown"
        assert plans[1].kind == "json"
        assert all(p.task_id == "t1" for p in plans)
        assert all(p.artifact_id.startswith("art_") for p in plans)


class TestArtifactRegistry:
    """Test 4: ArtifactRegistry writes artifact_records to ctx.metadata."""

    def test_register_writes_metadata(self):
        from agent.runtime.output.models import ArtifactRecord
        from agent.runtime.output.registry import ArtifactRegistry

        ctx = _make_ctx()
        record = ArtifactRecord(
            artifact_id="art_001",
            task_id="t1",
            kind="json",
            title="test artifact",
            status="registered",
        )
        registry = ArtifactRegistry()
        registry.register(ctx, record)
        assert "artifact_records" in ctx.metadata
        assert len(ctx.metadata["artifact_records"]) == 1
        assert ctx.metadata["artifact_records"][0]["artifact_id"] == "art_001"


class TestOutputSummary:
    """Test 5: OutputSummarizer writes output_summary to ctx.metadata."""

    def test_summarize_writes_metadata(self):
        from agent.runtime.output.models import ArtifactRecord, OutputSource
        from agent.runtime.output.summary import OutputSummarizer

        ctx = _make_ctx()
        sources = [OutputSource(source_id="s1")]
        records = [ArtifactRecord(artifact_id="a1", kind="json", title="data", status="registered")]
        summarizer = OutputSummarizer()
        out = summarizer.summarize(ctx, sources, records, task_id="t1")
        assert "output_summary" in ctx.metadata
        assert ctx.metadata["output_summary"]["task_id"] == "t1"
        assert len(ctx.metadata["output_summary"]["artifact_ids"]) == 1


# ═══════════════════════════════════════════════════════════════════════
# Round 9: Response Composer
# ═══════════════════════════════════════════════════════════════════════


class TestResponseComposer:
    """Test 6: ResponseComposer generates final_response."""

    def test_compose_writes_metadata(self):
        from agent.runtime.response.composer import ResponseComposer

        ctx = _make_ctx(metadata={
            "runtime_state_snapshot": {"active_task_id": "", "task_status": ""},
        })
        composer = ResponseComposer()
        resp = composer.compose(ctx)
        assert "final_response" in ctx.metadata
        assert ctx.metadata["final_response"]["response_type"] == "answer"


class TestResponseApproval:
    """Test 7: pending_approval → response_type=approval."""

    def test_pending_approval_triggers_approval(self):
        from agent.runtime.response.composer import ResponseComposer

        ctx = _make_ctx(metadata={
            "runtime_state_snapshot": {"active_task_id": "t1", "task_status": "running"},
            "pending_approvals": [{"action_id": "a1", "tool_id": "shell_exec", "risk": "high"}],
        })
        composer = ResponseComposer()
        resp = composer.compose(ctx)
        assert resp.response_type == "approval"
        assert ctx.metadata["final_response"]["response_type"] == "approval"


class TestResponseArtifact:
    """Test 8: artifact_records → response_type=artifact."""

    def test_artifact_records_trigger_artifact(self):
        from agent.runtime.response.composer import ResponseComposer

        ctx = _make_ctx(metadata={
            "runtime_state_snapshot": {"active_task_id": "t1", "task_status": ""},
            "artifact_records": [{"artifact_id": "a1", "kind": "json", "title": "data", "status": "created"}],
        })
        composer = ResponseComposer()
        resp = composer.compose(ctx)
        assert resp.response_type == "artifact"
        assert "a1" in resp.artifact_ids


# ═══════════════════════════════════════════════════════════════════════
# Round 10: Memory Writer
# ═══════════════════════════════════════════════════════════════════════


class TestMemoryWritePlanner:
    """Test 9: MemoryWritePlanner generates memory_write_plan."""

    def test_plan_writes_metadata(self):
        from agent.runtime.memory_write.planner import MemoryWritePlanner

        ctx = _make_ctx(metadata={
            "runtime_state_snapshot": {"active_task_id": "t1", "task_status": "completed"},
            "artifact_records": [
                {"artifact_id": "a1", "kind": "json", "title": "data", "summary": "result", "status": "created", "task_id": "t1"},
            ],
        })
        planner = MemoryWritePlanner()
        plan = planner.plan(ctx)
        assert "memory_write_plan" in ctx.metadata
        assert ctx.metadata["memory_write_plan"]["candidate_count"] >= 1


class TestMemoryRiskFilter:
    """Test 10: MemoryRiskFilter filters password/token/secret."""

    def test_filter_sensitive_content(self):
        from agent.runtime.memory_write.filter import MemoryRiskFilter
        from agent.runtime.memory_write.models import MemoryCandidate

        candidates = [
            MemoryCandidate(candidate_id="c1", content="normal learning about shell", memory_type="tool_learning"),
            MemoryCandidate(candidate_id="c2", content="password=secret123", memory_type="user_preference"),
            MemoryCandidate(candidate_id="c3", content="api_key=sk-abcdef1234567890123456", memory_type="tool_learning"),
        ]
        filt = MemoryRiskFilter()
        accepted, skipped = filt.filter(candidates)
        assert len(accepted) == 1
        assert accepted[0].candidate_id == "c1"
        assert len(skipped) == 2


# ═══════════════════════════════════════════════════════════════════════
# Round 11: Observability
# ═══════════════════════════════════════════════════════════════════════


class TestObservabilityCollector:
    """Test 11: ObservabilityCollector generates turn_trace."""

    def test_collect_writes_metadata(self):
        from agent.runtime.observability.collector import ObservabilityCollector

        ctx = _make_ctx(metadata={
            "scene_decision_status": "ok",
            "context_status": "ok",
            "task_signal": {"kind": "new_task", "reason": "user asked"},
            "runtime_state_snapshot": {"active_task_id": "t1", "active_step_id": "s1"},
            "action_trace": [
                {"type": "result", "action_id": "act_1", "status": "success", "summary": "ran cmd"},
            ],
            "output_summary": {"artifact_ids": ["a1"], "summary": "json output"},
            "final_response": {"response_type": "artifact"},
            "memory_write_plan": {"candidate_count": 1, "skipped_count": 0},
        })
        collector = ObservabilityCollector()
        trace = collector.collect(ctx)
        assert "turn_trace" in ctx.metadata
        assert ctx.metadata["turn_trace"]["event_count"] >= 5
        assert trace.turn_id == "turn_001"


class TestObservabilityExporter:
    """Test 11b: ObservabilityExporter exports compact JSON."""

    def test_export_json(self):
        from agent.runtime.observability.exporter import ObservabilityExporter
        from agent.runtime.observability.models import TurnTrace, ObservabilityEvent

        trace = TurnTrace(
            turn_id="t1",
            events=[ObservabilityEvent(event_id="e1", event_type="scene", status="ok")],
        )
        exporter = ObservabilityExporter()
        j = exporter.export_json(trace)
        assert '"turn_id":"t1"' in j
        d = exporter.export_dict(trace)
        assert d["event_count"] == 1


# ═══════════════════════════════════════════════════════════════════════
# Round 12: Truth Source
# ═══════════════════════════════════════════════════════════════════════


class TestTruthReport:
    """Test 12: TruthReport can be generated."""

    def test_report_writes_metadata(self):
        from agent.runtime.truth.report import TruthReporter

        ctx = _make_ctx(metadata={
            "visible_tools": ["shell_exec", "file_read"],
            "selected_skills": ["assistant_chat"],
            "context_status": "ok",
            "scene_decision_status": "ok",
            "runtime_state_status": "ok",
        })
        reporter = TruthReporter()
        report = reporter.report(ctx)
        assert "truth_report" in ctx.metadata
        assert "3.2.0" in report.version
        assert report.model_provider == "minimax"
        assert report.visible_tool_count == 2


class TestVersionTruth:
    """Test 12b: VersionTruth returns version string."""

    def test_version(self):
        from agent.runtime.truth.version import VersionTruth

        v = VersionTruth()
        assert "3.2.0" in v.full()
        assert v.version() == "3.2.0"


# ═══════════════════════════════════════════════════════════════════════
# Round 13: Stability Gate
# ═══════════════════════════════════════════════════════════════════════


class TestStabilityGate:
    """Test 13: StabilityGate generates stability_report."""

    def test_gate_full_pass(self):
        from agent.runtime.stability.gate import StabilityGate

        ctx = _make_ctx(metadata={
            "runtime_state_snapshot": {},
            "task_signal": {},
            "action_trace": [],
            "artifact_records": [],
            "output_summary": {},
            "final_response": {},
            "turn_trace": {},
            "memory_write_plan": {},
            "truth_report": {},
        })
        gate = StabilityGate()
        report = gate.check(ctx, source_dir=os.path.join(os.path.dirname(__file__), ".."))
        assert "stability_report" in ctx.metadata
        assert report.passed is True

    def test_gate_missing_metadata(self):
        from agent.runtime.stability.gate import StabilityGate

        ctx = _make_ctx()  # empty metadata
        gate = StabilityGate()
        report = gate.check(ctx)
        assert report.passed is False
        assert any("Missing metadata" in w for w in report.warnings)


class TestStabilityNoOldStage:
    """Test 14: StabilityGate checks old tool stage chain doesn't exist."""

    def test_no_old_stage_in_pipeline(self):
        from agent.runtime.stability.checks import check_no_old_stage_chain

        result = check_no_old_stage_chain(
            source_dir=os.path.join(os.path.dirname(__file__), "..")
        )
        assert result.passed is True


# ═══════════════════════════════════════════════════════════════════════
# Integration: Full pipeline metadata check
# ═══════════════════════════════════════════════════════════════════════


class TestFullPipelineMetadata:
    """Test 15: Total pipeline metadata keys are all present after full run."""

    def test_full_pipeline_metadata(self):
        from agent.runtime.output.collector import ResultCollector
        from agent.runtime.output.planner import ArtifactPlanner
        from agent.runtime.output.registry import ArtifactRegistry
        from agent.runtime.output.summary import OutputSummarizer
        from agent.runtime.output.writer import ArtifactWriter
        from agent.runtime.response.composer import ResponseComposer
        from agent.runtime.memory_write.planner import MemoryWritePlanner
        from agent.runtime.observability.collector import ObservabilityCollector
        from agent.runtime.truth.report import TruthReporter
        from agent.runtime.stability.gate import StabilityGate

        ctx = _make_ctx(metadata={
            "scene_decision_status": "ok",
            "context_status": "ok",
            "runtime_state_status": "ok",
            "runtime_state_snapshot": {"active_task_id": "t1", "active_step_id": "s1", "task_status": "running"},
            "task_signal": {"kind": "continue_task", "reason": "user continued"},
            "action_trace": [
                {"type": "result", "action_id": "act_1", "tool_id": "shell_exec", "result": "ok", "status": "success", "summary": "ran cmd"},
            ],
            "action_evidence_updates": [
                {"tool_id": "shell_exec", "summary": "command output"},
            ],
            "visible_tools": ["shell_exec"],
            "selected_skills": [],
        })

        # 1. Output Kernel
        sources = ResultCollector().collect(ctx)
        plans = ArtifactPlanner().plan(sources, task_id="t1", step_id="s1")
        writer = ArtifactWriter()
        records = [writer.write(p, sources) for p in plans]
        ArtifactRegistry().register_all(ctx, records)
        OutputSummarizer().summarize(ctx, sources, records, task_id="t1", step_id="s1")

        # 2. Response Composer
        ResponseComposer().compose(ctx)

        # 3. Memory Writer
        MemoryWritePlanner().plan(ctx)

        # 4. Observability
        ObservabilityCollector().collect(ctx)

        # 5. Truth Report
        TruthReporter().report(ctx)

        # 6. Stability Gate
        StabilityGate().check(ctx, source_dir=os.path.join(os.path.dirname(__file__), ".."))

        # Verify all expected keys
        expected_keys = [
            "runtime_state_snapshot",
            "task_signal",
            "artifact_records",
            "output_summary",
            "final_response",
            "memory_write_plan",
            "turn_trace",
            "truth_report",
            "stability_report",
        ]
        for key in expected_keys:
            assert key in ctx.metadata, f"Missing ctx.metadata['{key}']"

        assert ctx.metadata["stability_report"]["passed"] is True
