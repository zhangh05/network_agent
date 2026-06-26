# harness/test_memory_pipeline_optimization.py
"""Unit tests for the optimized memory write pipeline (L1/L2/L3).

Covers:
  - Writer persistence via ContextStore
  - Type-aware dedupe
  - CountCap enforcement
  - Gate mode switching
  - LLM Gate graceful fallback
"""

import json
import tempfile
import os
from dataclasses import dataclass, field

import pytest


# ── Helper: minimal TurnContext ─────────────────────────────────────────

@dataclass
class FakeTurnContext:
    turn_id: str = "t_test"
    session_id: str = "s_test"
    workspace_id: str = "test_w"
    metadata: dict = field(default_factory=dict)


def make_ctx(**meta) -> FakeTurnContext:
    ctx = FakeTurnContext()
    ctx.metadata = dict(meta)
    ctx.metadata.setdefault("action_trace", [])
    ctx.metadata.setdefault("artifact_records", [])
    return ctx


# ── Test: Writer ────────────────────────────────────────────────────────

class TestWriter:
    def test_writer_limits_max_per_turn(self, monkeypatch):
        """Writer should not write more than MAX_WRITE_PER_TURN candidates."""
        from agent.runtime.memory_write.writer import MemoryWriter, MAX_WRITE_PER_TURN
        from agent.runtime.memory_write.models import MemoryCandidate, MemoryWritePlan

        # Mock store.put to accept anything
        written = []
        def fake_put(self, record):
            written.append(record)
            return record.get("memory_id", "fake_id")
        monkeypatch.setattr("memory.store.get_store", lambda ws: type("S", (), {"put": fake_put})())

        candidates = [
            MemoryCandidate(candidate_id=f"mc_{i}", memory_type="test", content=f"content_{i}", confidence=1.0)
            for i in range(MAX_WRITE_PER_TURN + 2)
        ]
        plan = MemoryWritePlan(candidates=candidates)

        result = MemoryWriter().write(make_ctx(), plan, workspace_id="test_w")
        assert result["status"] in ("ok", "partial")
        assert result["written_count"] == MAX_WRITE_PER_TURN
        assert len(written) == MAX_WRITE_PER_TURN

    def test_writer_empty_plan(self):
        """Writer should handle empty plan gracefully."""
        from agent.runtime.memory_write.writer import MemoryWriter
        from agent.runtime.memory_write.models import MemoryWritePlan

        plan = MemoryWritePlan(candidates=[])
        result = MemoryWriter().write(make_ctx(), plan, workspace_id="test_w")
        assert result["status"] == "empty"
        assert result["written_count"] == 0

    def test_writer_sorts_by_confidence(self, monkeypatch):
        """Writer should persist highest-confidence candidates first."""
        from agent.runtime.memory_write.writer import MemoryWriter, MAX_WRITE_PER_TURN
        from agent.runtime.memory_write.models import MemoryCandidate, MemoryWritePlan

        written = []
        def fake_put_ws(self, record):
            written.append(record)
            return record.get("memory_id", "fake_id")
        monkeypatch.setattr("memory.store.get_store", lambda ws: type("S", (), {"put": fake_put_ws})())

        candidates = [
            MemoryCandidate(candidate_id="mc_low", memory_type="test", content="low", confidence=0.1),
            MemoryCandidate(candidate_id="mc_mid", memory_type="test", content="mid", confidence=0.5),
            MemoryCandidate(candidate_id="mc_high", memory_type="test", content="high", confidence=1.0),
            MemoryCandidate(candidate_id="mc_mid2", memory_type="test", content="mid2", confidence=0.5),
        ]
        plan = MemoryWritePlan(candidates=candidates)

        result = MemoryWriter().write(make_ctx(), plan, workspace_id="test_w")
        assert result["written_count"] == MAX_WRITE_PER_TURN
        assert written[0]["memory_id"] == "mc_high"
        # sorted by confidence descending
        assert written[0]["confidence"] == 1.0


# ── Test: Dedupe ────────────────────────────────────────────────────────

class TestDedupe:
    def test_exact_match_dedupe(self):
        """Exact same content → deduped."""
        from agent.runtime.memory_write.dedupe import MemoryDedupe
        from agent.runtime.memory_write.models import MemoryCandidate

        dedupe = MemoryDedupe()
        candidates = [
            MemoryCandidate(candidate_id="mc_a", memory_type="test", content="same content"),
            MemoryCandidate(candidate_id="mc_b", memory_type="test", content="same content"),
        ]
        result = dedupe.dedupe(candidates)
        assert len(result) == 1

    def test_type_aware_threshold(self):
        """Same type with high prefix overlap → deduped (threshold=0.80)."""
        from agent.runtime.memory_write.dedupe import MemoryDedupe
        from agent.runtime.memory_write.models import MemoryCandidate

        dedupe = MemoryDedupe()
        # Same type, common prefix covers >80% of shorter string
        candidates = [
            MemoryCandidate(candidate_id="mc_a", memory_type="task_pattern",
                          content="Task completed successfully"),
            MemoryCandidate(candidate_id="mc_b", memory_type="task_pattern",
                          content="Task completed successfully with extra details here"),
        ]
        # shorter = 26 ("Task completed successfully")
        # common_prefix = 26 → 26/26 = 1.0 > 0.80 → dup
        result = dedupe.dedupe(candidates)
        assert len(result) == 1

    def test_cross_type_preserved(self):
        """Different types with similar (not identical) content are preserved."""
        from agent.runtime.memory_write.dedupe import MemoryDedupe
        from agent.runtime.memory_write.models import MemoryCandidate

        dedupe = MemoryDedupe()
        candidates = [
            MemoryCandidate(candidate_id="mc_a", memory_type="artifact_summary",
                          content="Result: search found 10 items matching the query"),
            MemoryCandidate(candidate_id="mc_b", memory_type="task_pattern",
                          content="Result: search completed successfully"),
        ]
        # "Result: search " = 15 common prefix
        # shorter = min(44, 33) = 33
        # 15/33 = 0.455 < 0.90 → not duped (cross-type threshold is higher)
        result = dedupe.dedupe(candidates)
        assert len(result) == 2

    def test_empty_content_skipped(self):
        """Empty content → skipped."""
        from agent.runtime.memory_write.dedupe import MemoryDedupe
        from agent.runtime.memory_write.models import MemoryCandidate

        dedupe = MemoryDedupe()
        candidates = [
            MemoryCandidate(candidate_id="mc_a", memory_type="test", content=""),
            MemoryCandidate(candidate_id="mc_b", memory_type="test", content="valid"),
        ]
        result = dedupe.dedupe(candidates)
        assert len(result) == 1
        assert result[0].content == "valid"


# ── Test: CountCap ──────────────────────────────────────────────────────

class TestCountCap:
    def test_per_type_cap(self):
        """Per-type limits are enforced."""
        from agent.runtime.memory_write.count_cap import MemoryCountCap
        from agent.runtime.memory_write.models import MemoryCandidate

        cap = MemoryCountCap()
        candidates = [
            MemoryCandidate(candidate_id=f"mc_err_{i}", memory_type="error_lesson",
                          content=f"error_{i}", confidence=float(i))
            for i in range(20)  # 20 candidates, cap is 10
        ]
        result = cap.apply_to_candidates(candidates)
        assert len(result) == 10
        # highest confidence first
        assert result[0].confidence == 19.0

    def test_global_cap(self):
        """Global cap kicks in when total exceeds MAX_TOTAL_MEMORY."""
        from agent.runtime.memory_write.count_cap import MemoryCountCap, MAX_TOTAL_MEMORY
        from agent.runtime.memory_write.models import MemoryCandidate

        cap = MemoryCountCap()
        candidates = [
            MemoryCandidate(candidate_id=f"mc_{i}", memory_type="test",
                          content=f"content_{i}", confidence=float(i % 10))
            for i in range(MAX_TOTAL_MEMORY + 100)
        ]
        result = cap.apply_to_candidates(candidates)
        assert len(result) <= MAX_TOTAL_MEMORY


# ── Test: Gate Mode ─────────────────────────────────────────────────────

class TestGateMode:
    def test_default_rule_only(self):
        """Default mode is rule_only."""
        from agent.runtime.memory_write.gate import get_gate_mode, MemoryGateMode
        mode = get_gate_mode("nonexistent_workspace")
        assert mode == MemoryGateMode.RULE_ONLY

    def test_llm_first_config(self):
        """Workspace with memory_gating=llm_first returns LLM_FIRST mode."""
        from agent.runtime.memory_write.gate import get_gate_mode, MemoryGateMode

        # It will try to read workspace state which doesn't exist → returns {}
        # So only way to test is via mock
        import workspace.manager
        original = workspace.manager.get_workspace_state
        workspace.manager.get_workspace_state = lambda ws: {"memory_gating": "llm_first"}
        try:
            mode = get_gate_mode("test_w")
            assert mode == MemoryGateMode.LLM_FIRST
        finally:
            workspace.manager.get_workspace_state = original


# ── Test: Pipeline integraion ───────────────────────────────────────────

class TestPipelineIntegration:
    def test_planner_extracts_from_artifact(self):
        """Planner extracts candidates from artifact_records."""
        from agent.runtime.memory_write.planner import MemoryWritePlanner

        planner = MemoryWritePlanner()
        ctx = make_ctx(
            artifact_records=[
                {"status": "created", "title": "test report", "kind": "report",
                 "summary": "A test report", "task_id": "t_1"},
            ]
        )
        candidates = planner._extract_candidates(ctx)
        # v3.8: artifact_summary extraction disabled — produces no candidates
        assert len(candidates) == 0

    def test_planner_extracts_from_task(self):
        """Planner extracts candidate from completed task."""
        from agent.runtime.memory_write.planner import MemoryWritePlanner

        planner = MemoryWritePlanner()
        ctx = make_ctx(
            runtime_state_snapshot={
                "active_task_id": "t_1",
                "active_task_title": "search task",
                "task_status": "completed",
            }
        )
        candidates = planner._extract_candidates(ctx)
        task_cands = [c for c in candidates if c.memory_type == "task_pattern"]
        assert len(task_cands) == 1
        assert "search task" in task_cands[0].content

    def test_planner_extracts_from_errors(self):
        """Planner extracts candidate from failed actions."""
        from agent.runtime.memory_write.planner import MemoryWritePlanner

        planner = MemoryWritePlanner()
        ctx = make_ctx(
            action_trace=[
                {"action_id": "a_1", "status": "failed", "error": "Connection timeout after 30s"},
            ]
        )
        candidates = planner._extract_candidates(ctx)
        err_cands = [c for c in candidates if c.memory_type == "error_lesson"]
        assert len(err_cands) == 1
        assert "timeout" in err_cands[0].content.lower()

    def test_planner_skips_trivial_errors(self):
        """Planner skips failed actions with too-short error messages."""
        from agent.runtime.memory_write.planner import MemoryWritePlanner

        planner = MemoryWritePlanner()
        ctx = make_ctx(
            action_trace=[
                {"action_id": "a_1", "status": "failed", "error": "err"},
            ]
        )
        candidates = planner._extract_candidates(ctx)
        err_cands = [c for c in candidates if c.memory_type == "error_lesson"]
        assert len(err_cands) == 0


# ── Test: LLM Gate ──────────────────────────────────────────────────────

class TestLLMGate:
    def test_serialize_candidates(self):
        """Candidate serialization is JSON-safe."""
        from agent.runtime.memory_write.llm_gate import MemoryLLMGate
        from agent.runtime.memory_write.models import MemoryCandidate

        gate = MemoryLLMGate()
        candidates = [
            MemoryCandidate(candidate_id="mc_1", memory_type="task_pattern",
                          content="Task completed", confidence=0.7),
        ]
        serialized = gate._serialize_candidates(candidates)
        data = json.loads(serialized)
        assert len(data) == 1
        assert data[0]["id"] == "mc_1"
        assert data[0]["type"] == "task_pattern"

    def test_parse_response_valid(self):
        """Parse well-formed LLM response."""
        from agent.runtime.memory_write.llm_gate import MemoryLLMGate

        gate = MemoryLLMGate()
        raw = json.dumps({
            "candidates": [
                {"id": "mc_1", "score": 4, "keep": True, "summary": "Task completed"},
                {"id": "mc_2", "score": 1, "keep": False, "summary": ""},
            ]
        })
        results = gate._parse_response(raw, [])
        assert len(results) == 2
        assert results[0]["keep"] is True
        assert results[1]["keep"] is False

    def test_parse_response_with_code_fence(self):
        """Parse LLM response wrapped in ```json ... ```."""
        from agent.runtime.memory_write.llm_gate import MemoryLLMGate

        gate = MemoryLLMGate()
        raw = '```json\n{"candidates": [{"id": "mc_1", "score": 5, "keep": true, "summary": "Great"}]}\n```'
        results = gate._parse_response(raw, [])
        assert len(results) == 1
        assert results[0]["keep"] is True
        assert results[0]["score"] == 5

    def test_gate_batch_limit(self, monkeypatch):
        """LLM Gate caps batch at MAX_BATCH_SIZE."""
        from agent.runtime.memory_write.llm_gate import MemoryLLMGate, MAX_BATCH_SIZE
        from agent.runtime.memory_write.models import MemoryCandidate

        # Mock _call_llm to return a simple response
        def fake_call(self, messages):
            return json.dumps({"candidates": [
                {"id": f"mc_{i}", "score": 3, "keep": True, "summary": f"item {i}"}
                for i in range(MAX_BATCH_SIZE + 5)
            ]})

        monkeypatch.setattr(MemoryLLMGate, "_call_llm", fake_call)

        gate = MemoryLLMGate()
        candidates = [
            MemoryCandidate(candidate_id=f"mc_{i}", memory_type="test",
                          content=f"content_{i}", confidence=0.5)
            for i in range(MAX_BATCH_SIZE + 5)
        ]
        accepted, skipped = gate.gate(candidates)

        # Only MAX_BATCH_SIZE were sent to LLM
        assert len(accepted) + len(skipped) <= MAX_BATCH_SIZE

    def test_gate_fallback_on_llm_error(self, monkeypatch):
        """LLM Gate falls back gracefully on LLM error."""
        from agent.runtime.memory_write.llm_gate import MemoryLLMGate
        from agent.runtime.memory_write.models import MemoryCandidate

        def fake_call_fail(self, messages):
            raise RuntimeError("LLM unreachable")

        monkeypatch.setattr(MemoryLLMGate, "_call_llm", fake_call_fail)

        gate = MemoryLLMGate()
        candidates = [
            MemoryCandidate(candidate_id="mc_1", memory_type="test",
                          content="test", confidence=0.5),
        ]
        accepted, skipped = gate.gate(candidates)
        # All candidates kept on LLM failure
        assert len(accepted) == 1
        assert len(skipped) == 0
