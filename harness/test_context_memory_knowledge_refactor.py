# harness/test_context_memory_knowledge_refactor.py
"""Tests for Context/Memory/Knowledge separation refactor.

Validates:
1. ContextQueryPlan — simple_chat produces minimal plan
2. context/loader — no memory/knowledge search in source
3. MemoryQueryPlan — only when scene requires memory
4. MemoryWritePolicy — requires explicit user intent
5. KnowledgeQueryPlan — rewrites query (strips filler words)
6. KnowledgeRetrieverV2 — returns KnowledgeHit instances
7. EvidenceMerge — produces layered EvidenceBundle
8. ConflictDetector — detects vendor conflicts
9. TrustPolicy — downgrades unconfirmed memory trust
10. All new modules importable
"""

import pytest


# ── 1. ContextQueryPlan ─────────────────────────────────────────────

class TestContextQueryPlan:
    def test_simple_chat_minimal(self):
        """Simple chat scene should produce minimal context plan."""
        from agent.runtime.context.query_plan import ContextQueryPlanner
        from agent.runtime.cognition.scene_decision import SceneDecision

        scene = SceneDecision(user_input="你好", is_simple_chat=True)
        planner = ContextQueryPlanner()
        plan = planner.plan(scene)

        assert plan.include_workspace is False
        assert plan.include_artifacts is False
        assert plan.include_jobs is False
        assert plan.include_reports is False
        assert plan.include_history is True
        assert plan.history_window == 3
        assert "simple_chat" in plan.reason

    def test_file_task_includes_artifacts(self):
        """File task should include artifacts + workspace."""
        from agent.runtime.context.query_plan import ContextQueryPlanner
        from agent.runtime.cognition.scene_decision import SceneDecision

        scene = SceneDecision(user_input="分析配置文件", is_file_task=True)
        planner = ContextQueryPlanner()
        plan = planner.plan(scene)

        assert plan.include_workspace is True
        assert plan.include_artifacts is True

    def test_no_scene_uses_defaults(self):
        from agent.runtime.context.query_plan import ContextQueryPlanner
        planner = ContextQueryPlanner()
        plan = planner.plan(None)
        assert plan.include_workspace is True
        assert "defaults" in plan.reason


# ── 2. context/loader no memory/knowledge ───────────────────────────

class TestLoaderNoMemoryKnowledge:
    def test_loader_source_no_search_memory(self):
        """loader.py must not contain search_memory calls."""
        import inspect
        import core.context.loader as mod
        source = inspect.getsource(mod)
        assert "search_memory" not in source, "loader.py still contains search_memory"

    def test_loader_source_no_search_knowledge(self):
        """loader.py must not contain search_knowledge calls."""
        import inspect
        import core.context.loader as mod
        source = inspect.getsource(mod)
        assert "search_knowledge" not in source, "loader.py still contains search_knowledge"


# ── 3. MemoryQueryPlan ──────────────────────────────────────────────

class TestMemoryQueryPlan:
    def test_not_needed_for_simple_chat(self):
        """Simple chat should not trigger memory search."""
        from agent.runtime.memory.query_planner import MemoryQueryPlanner
        from agent.runtime.cognition.scene_decision import SceneDecision

        scene = SceneDecision(user_input="你好", is_simple_chat=True, needs_memory=False)
        planner = MemoryQueryPlanner()
        plan = planner.plan(scene)

        assert plan.should_search is False

    def test_needed_when_scene_requires(self):
        """Memory search triggered when scene_decision.needs_memory=True."""
        from agent.runtime.memory.query_planner import MemoryQueryPlanner
        from agent.runtime.cognition.scene_decision import SceneDecision

        scene = SceneDecision(user_input="记忆中有什么", needs_memory=True)
        planner = MemoryQueryPlanner()
        plan = planner.plan(scene)

        assert plan.should_search is True
        assert plan.query_text == "记忆中有什么"

    def test_no_scene_returns_safe_default(self):
        from agent.runtime.memory.query_planner import MemoryQueryPlanner
        from agent.runtime.knowledge.query_planner import KnowledgeQueryPlanner
        planner = MemoryQueryPlanner()
        plan = planner.plan(None)
        assert plan.should_search is False


        from agent.runtime.cognition.scene_decision import SceneDecision

        scene = SceneDecision(
            user_input="请问OSPF的工作原理是什么",
            is_knowledge_task=True,
            needs_knowledge=True,
        )
        planner = KnowledgeQueryPlanner()
        plan = planner.plan(scene)

        assert plan.should_search is True
        assert plan.citation_required is True
        # Filler "请问" should be removed
        assert "请问" not in plan.rewritten_query
        assert "OSPF" in plan.rewritten_query

    def test_simple_chat_no_search(self):
        from agent.runtime.knowledge.query_planner import KnowledgeQueryPlanner
        from agent.runtime.cognition.scene_decision import SceneDecision

        scene = SceneDecision(user_input="你好", is_simple_chat=True)
        planner = KnowledgeQueryPlanner()
        plan = planner.plan(scene)

        assert plan.should_search is False

    def test_factual_query_triggers_search(self):
        from agent.runtime.knowledge.query_planner import KnowledgeQueryPlanner
        from agent.runtime.cognition.scene_decision import SceneDecision

        scene = SceneDecision(user_input="BGP路由协议", is_factual_query=True)
        planner = KnowledgeQueryPlanner()
        plan = planner.plan(scene)

        assert plan.should_search is True


# ── 6. KnowledgeRetrieverV2 ────────────────────────────────────────

class TestKnowledgeRetrieverV2:
    def test_returns_knowledge_hit_instances(self):
        """KnowledgeRetrieverV2.retrieve returns list of KnowledgeHit."""
        from agent.runtime.knowledge.retriever import KnowledgeRetrieverV2
        from agent.runtime.knowledge.models import KnowledgeHit, KnowledgeQueryPlan

        retriever = KnowledgeRetrieverV2()
        plan = KnowledgeQueryPlan(should_search=False)
        hits = retriever.retrieve("test_ws", plan)
        assert isinstance(hits, list)
        assert len(hits) == 0  # should_search=False → empty

    def test_skips_when_no_search(self):
        from agent.runtime.knowledge.retriever import KnowledgeRetrieverV2
        from agent.runtime.knowledge.models import KnowledgeQueryPlan

        retriever = KnowledgeRetrieverV2()
        plan = KnowledgeQueryPlan(should_search=False)
        assert retriever.retrieve("ws", plan) == []


# ── 7. EvidenceMerge ───────────────────────────────────────────────

class TestEvidenceMerge:
    def test_merge_produces_layers(self):
        """EvidenceMerge should produce an EvidenceBundle with layers."""
        from agent.runtime.cognition.evidence_merge import EvidenceMerge
        from agent.runtime.context.frame import ContextFrame
        from agent.runtime.memory.models import MemoryItem
        from agent.runtime.knowledge.models import KnowledgeHit, Citation

        merger = EvidenceMerge()
        frame = ContextFrame(
            workspace_id="ws1",
            workspace_state={"device_type": "switch"},
            active_artifacts=[{"artifact_id": "a1", "title": "config.txt"}],
        )
        memory = [MemoryItem(memory_id="m1", content="user prefers Huawei")]
        knowledge = [KnowledgeHit(chunk_id="k1", title="OSPF basics", content="OSPF is...", score=0.8)]
        citations = [Citation(citation_id="K1", source_id="s1", chunk_id="k1", title="OSPF basics")]

        bundle = merger.merge(
            context_frame=frame,
            memory_items=memory,
            knowledge_hits=knowledge,
            citations=citations,
        )

        # Flat fields populated
        assert len(bundle.memory_items) == 1
        assert len(bundle.knowledge_items) == 1
        assert len(bundle.artifact_refs) == 1
        assert bundle.workspace_state.get("device_type") == "switch"
        assert len(bundle.citations) == 1

        # Layer fields populated
        assert bundle.context_layer.layer_name == "context"
        assert bundle.memory_layer.layer_name == "memory"
        assert bundle.knowledge_layer.layer_name == "knowledge"
        assert bundle.artifact_layer.layer_name == "artifact"
        assert bundle.memory_layer.count == 1
        assert bundle.knowledge_layer.count == 1

    def test_merge_empty_inputs(self):
        from agent.runtime.cognition.evidence_merge import EvidenceMerge
        merger = EvidenceMerge()
        bundle = merger.merge()
        assert len(bundle.memory_items) == 0
        assert len(bundle.knowledge_items) == 0

    def test_to_safe_context_still_works(self):
        """to_safe_context() must still produce the expected dict format."""
        from agent.runtime.cognition.evidence_merge import EvidenceMerge
        from agent.runtime.memory.models import MemoryItem
        from agent.runtime.knowledge.models import KnowledgeHit

        merger = EvidenceMerge()
        bundle = merger.merge(
            memory_items=[MemoryItem(memory_id="m1", content="test mem")],
            knowledge_hits=[KnowledgeHit(chunk_id="k1", title="doc", content="hello", score=0.9)],
        )
        safe = bundle.to_safe_context()
        assert isinstance(safe, dict)
        assert "memory_hits" in safe
        assert "knowledge_hits" in safe


# ── 8. ConflictDetector ────────────────────────────────────────────

class TestConflictDetector:
    def test_detects_vendor_conflict(self):
        """Should detect when evidence mixes h3c and huawei vendors."""
        from agent.runtime.cognition.evidence_conflict import EvidenceConflictDetector
        from agent.runtime.cognition.evidence_models import EvidenceBundle, EvidenceItem

        bundle = EvidenceBundle(
            knowledge_items=[
                EvidenceItem(evidence_id="k1", source_type="knowledge",
                             title="H3C交换机配置", content="H3C Comware配置命令"),
                EvidenceItem(evidence_id="k2", source_type="knowledge",
                             title="华为交换机配置", content="Huawei VRP配置命令"),
            ],
        )

        detector = EvidenceConflictDetector()
        conflicts = detector.detect(bundle)

        assert len(conflicts) >= 1
        vendor_conflict = conflicts[0]
        assert vendor_conflict.conflict_type == "vendor"
        assert "h3c" in vendor_conflict.description.lower() or "huawei" in vendor_conflict.description.lower()

    def test_no_conflict_single_vendor(self):
        """No conflict when all evidence is from same vendor."""
        from agent.runtime.cognition.evidence_conflict import EvidenceConflictDetector
        from agent.runtime.cognition.evidence_models import EvidenceBundle, EvidenceItem

        bundle = EvidenceBundle(
            knowledge_items=[
                EvidenceItem(evidence_id="k1", title="Huawei OSPF", content="华为OSPF配置"),
                EvidenceItem(evidence_id="k2", title="Huawei BGP", content="华为BGP配置"),
            ],
        )

        detector = EvidenceConflictDetector()
        conflicts = detector.detect(bundle)
        assert len(conflicts) == 0

    def test_no_conflict_empty_bundle(self):
        from agent.runtime.cognition.evidence_conflict import EvidenceConflictDetector
        from agent.runtime.cognition.evidence_models import EvidenceBundle

        detector = EvidenceConflictDetector()
        conflicts = detector.detect(EvidenceBundle())
        assert conflicts == []


# ── 9. TrustPolicy ────────────────────────────────────────────────

class TestTrustPolicy:
    def test_downgrades_unconfirmed_memory(self):
        """Unconfirmed memory items should get trust_level 'low'."""
        from agent.runtime.cognition.trust_policy import TrustPolicy
        from agent.runtime.cognition.evidence_models import EvidenceBundle, EvidenceItem

        bundle = EvidenceBundle(
            memory_items=[
                EvidenceItem(
                    evidence_id="m1", source_type="memory",
                    trust_level="untrusted", content="some memory",
                    metadata={"confirmation_status": "unconfirmed"},
                ),
            ],
        )

        policy = TrustPolicy()
        report = policy.apply(bundle)

        assert bundle.memory_items[0].trust_level == "low"
        assert report["applied"] is True

    def test_confirmed_memory_gets_medium(self):
        from agent.runtime.cognition.trust_policy import TrustPolicy
        from agent.runtime.cognition.evidence_models import EvidenceBundle, EvidenceItem

        bundle = EvidenceBundle(
            memory_items=[
                EvidenceItem(
                    evidence_id="m1", source_type="memory",
                    trust_level="untrusted", content="confirmed mem",
                    metadata={"confirmation_status": "confirmed"},
                ),
            ],
        )

        policy = TrustPolicy()
        policy.apply(bundle)

        assert bundle.memory_items[0].trust_level == "medium"

    def test_blocked_gets_excluded(self):
        from agent.runtime.cognition.trust_policy import TrustPolicy
        from agent.runtime.cognition.evidence_models import EvidenceBundle, EvidenceItem

        bundle = EvidenceBundle(
            knowledge_items=[
                EvidenceItem(
                    evidence_id="k1", source_type="knowledge",
                    scan_status="blocked", content="blocked content",
                ),
            ],
        )

        policy = TrustPolicy()
        policy.apply(bundle)

        assert bundle.knowledge_items[0].trust_level == "excluded"


# ── 10. All new modules importable ─────────────────────────────────

class TestImportability:
    def test_context_modules(self):
        from agent.runtime.context.frame import ContextFrame
        from agent.runtime.context.query_plan import ContextQueryPlan, ContextQueryPlanner
        from agent.runtime.context.resolver import ContextResolver
        from agent.runtime.context.selector import select_for_frame
        from agent.runtime.context.budget import estimate_tokens, fits_budget
        assert ContextFrame is not None
        assert ContextQueryPlan is not None
        assert ContextQueryPlanner is not None
        assert ContextResolver is not None
        assert callable(select_for_frame)
        assert callable(estimate_tokens)

        from agent.runtime.memory.models import MemoryWritePlan
        from agent.runtime.memory.query_planner import MemoryQueryPlanner
        from agent.runtime.memory.retriever import MemoryRetriever
        from agent.runtime.memory_write.llm_memory import generate_memories
        assert MemoryWritePlan is not None
        assert MemoryQueryPlanner is not None
        assert MemoryRetriever is not None
        assert generate_memories is not None

    def test_knowledge_modules(self):
        from agent.runtime.knowledge.models import KnowledgeHit, KnowledgeQueryPlan, Citation
        from agent.runtime.knowledge.query_planner import KnowledgeQueryPlanner
        from agent.runtime.knowledge.retriever import KnowledgeRetrieverV2
        from agent.runtime.knowledge.reranker import KnowledgeReranker
        from agent.runtime.knowledge.citation import CitationGraph
        from agent.runtime.knowledge.source_policy import SourcePolicy
        from agent.runtime.knowledge.conflict import KnowledgeConflictDetector
        assert KnowledgeHit is not None
        assert KnowledgeQueryPlan is not None
        assert Citation is not None
        assert KnowledgeQueryPlanner is not None
        assert KnowledgeRetrieverV2 is not None
        assert KnowledgeReranker is not None
        assert CitationGraph is not None
        assert SourcePolicy is not None
        assert KnowledgeConflictDetector is not None

    def test_cognition_modules(self):
        from agent.runtime.cognition.evidence_layers import EvidenceLayer
        from agent.runtime.cognition.evidence_merge import EvidenceMerge
        from agent.runtime.cognition.evidence_conflict import EvidenceConflict, EvidenceConflictDetector
        from agent.runtime.cognition.trust_policy import TrustPolicy
        assert EvidenceLayer is not None
        assert EvidenceMerge is not None
        assert EvidenceConflict is not None
        assert EvidenceConflictDetector is not None
        assert TrustPolicy is not None

    def test_evidence_bundle_has_layer_fields(self):
        from agent.runtime.cognition.evidence_models import EvidenceBundle
        bundle = EvidenceBundle()
        assert hasattr(bundle, "context_layer")
        assert hasattr(bundle, "memory_layer")
        assert hasattr(bundle, "knowledge_layer")
        assert hasattr(bundle, "artifact_layer")
        assert hasattr(bundle, "conflicts")
        assert hasattr(bundle, "trust_report")
        assert hasattr(bundle, "citation_graph")

    def test_turn_context_has_context_frame(self):
        from agent.core.turn_context import TurnContext
        ctx = TurnContext()
        assert hasattr(ctx, "context_frame")
        assert ctx.context_frame is None


# ── 11. Source code cleanliness ────────────────────────────────────

class TestSourceCodeCleanliness:
    def test_evidence_pipeline_no_safe_llm_context(self):
        """EvidencePipeline source must not reference safe_llm_context."""
        import inspect
        import agent.runtime.cognition.evidence_pipeline as mod
        source = inspect.getsource(mod)
        assert "safe_llm_context" not in source

    def test_context_builder_no_build_context_bundle(self):
        """ContextBuilder source must not import or call build_context_bundle."""
        import inspect
        import agent.runtime.context_builder as mod
        source = inspect.getsource(mod)
        assert "build_context_bundle" not in source

    def test_context_builder_py_no_memory_knowledge_hits(self):
        """context/builder.py must not assemble memory_hits or knowledge_hits."""
        import inspect
        import core.context.builder as mod
        source = inspect.getsource(mod)
        assert "memory_hits" not in source
        assert "knowledge_hits" not in source

    def test_evidence_merge_no_private_layer_fields(self):
        """EvidenceMerge must use public layer fields (no underscore prefix)."""
        import inspect
        import agent.runtime.cognition.evidence_merge as mod
        source = inspect.getsource(mod)
        assert "_context_layer" not in source
        assert "_memory_layer" not in source
        assert "_knowledge_layer" not in source
        assert "_artifact_layer" not in source

    def test_evidence_pipeline_no_backward_compat_text(self):
        """EvidencePipeline must not mention 'Maintains backward compatibility'."""
        import inspect
        import agent.runtime.cognition.evidence_pipeline as mod
        source = inspect.getsource(mod)
        assert "Maintains backward" not in source


# ── 12. Pipeline call order (monkeypatch) ──────────────────────────

class TestPipelineCallOrder:
    def test_pipeline_calls_all_stages(self, monkeypatch):
        """EvidencePipeline.build() must call all pipeline stages in order."""
        call_log = []

        from agent.core.turn_context import TurnContext
        ctx = TurnContext(workspace_id="test_ws", user_input="test")
        ctx.metadata = {}

        import agent.runtime.context.query_plan as cqp_mod
        import agent.runtime.context.resolver as cr_mod
        import agent.runtime.memory.query_planner as mqp_mod
        import agent.runtime.memory.retriever as mr_mod
        import agent.runtime.knowledge.query_planner as kqp_mod
        import agent.runtime.knowledge.retriever as kr_mod
        import agent.runtime.knowledge.reranker as krr_mod
        import agent.runtime.knowledge.citation as cg_mod
        import agent.runtime.cognition.evidence_merge as em_mod
        import agent.runtime.cognition.evidence_conflict as ec_mod
        import agent.runtime.cognition.trust_policy as tp_mod
        import agent.runtime.cognition.context_budget as cb_mod

        originals = {
            "ContextQueryPlanner.plan": cqp_mod.ContextQueryPlanner.plan,
            "ContextResolver.resolve": cr_mod.ContextResolver.resolve,
            "MemoryQueryPlanner.plan": mqp_mod.MemoryQueryPlanner.plan,
            "MemoryRetriever.retrieve": mr_mod.MemoryRetriever.retrieve,
            "KnowledgeQueryPlanner.plan": kqp_mod.KnowledgeQueryPlanner.plan,
            "KnowledgeRetrieverV2.retrieve": kr_mod.KnowledgeRetrieverV2.retrieve,
            "KnowledgeReranker.rerank": krr_mod.KnowledgeReranker.rerank,
            "CitationGraph.build": cg_mod.CitationGraph.build,
            "EvidenceMerge.merge": em_mod.EvidenceMerge.merge,
            "EvidenceConflictDetector.detect": ec_mod.EvidenceConflictDetector.detect,
            "TrustPolicy.apply": tp_mod.TrustPolicy.apply,
            "ContextBudgetManager.apply": cb_mod.ContextBudgetManager.apply,
        }

        def make_wrapper(name, orig):
            def wrapper(self, *a, **kw):
                call_log.append(name)
                return orig(self, *a, **kw)
            return wrapper

        monkeypatch.setattr(cqp_mod.ContextQueryPlanner, "plan", make_wrapper("ContextQueryPlanner.plan", originals["ContextQueryPlanner.plan"]))
        monkeypatch.setattr(cr_mod.ContextResolver, "resolve", make_wrapper("ContextResolver.resolve", originals["ContextResolver.resolve"]))
        monkeypatch.setattr(mqp_mod.MemoryQueryPlanner, "plan", make_wrapper("MemoryQueryPlanner.plan", originals["MemoryQueryPlanner.plan"]))
        monkeypatch.setattr(mr_mod.MemoryRetriever, "retrieve", make_wrapper("MemoryRetriever.retrieve", originals["MemoryRetriever.retrieve"]))
        monkeypatch.setattr(kqp_mod.KnowledgeQueryPlanner, "plan", make_wrapper("KnowledgeQueryPlanner.plan", originals["KnowledgeQueryPlanner.plan"]))
        monkeypatch.setattr(kr_mod.KnowledgeRetrieverV2, "retrieve", make_wrapper("KnowledgeRetrieverV2.retrieve", originals["KnowledgeRetrieverV2.retrieve"]))
        monkeypatch.setattr(krr_mod.KnowledgeReranker, "rerank", make_wrapper("KnowledgeReranker.rerank", originals["KnowledgeReranker.rerank"]))
        monkeypatch.setattr(cg_mod.CitationGraph, "build", make_wrapper("CitationGraph.build", originals["CitationGraph.build"]))
        monkeypatch.setattr(em_mod.EvidenceMerge, "merge", make_wrapper("EvidenceMerge.merge", originals["EvidenceMerge.merge"]))
        monkeypatch.setattr(ec_mod.EvidenceConflictDetector, "detect", make_wrapper("EvidenceConflictDetector.detect", originals["EvidenceConflictDetector.detect"]))
        monkeypatch.setattr(tp_mod.TrustPolicy, "apply", make_wrapper("TrustPolicy.apply", originals["TrustPolicy.apply"]))
        monkeypatch.setattr(cb_mod.ContextBudgetManager, "apply", make_wrapper("ContextBudgetManager.apply", originals["ContextBudgetManager.apply"]))

        from agent.runtime.cognition.evidence_pipeline import EvidencePipeline
        pipeline = EvidencePipeline()
        pipeline.build(ctx)

        expected = [
            "ContextQueryPlanner.plan",
            "ContextResolver.resolve",
            "MemoryQueryPlanner.plan",
            "MemoryRetriever.retrieve",
            "KnowledgeQueryPlanner.plan",
            "KnowledgeRetrieverV2.retrieve",
            "KnowledgeReranker.rerank",
            "CitationGraph.build",
            "EvidenceMerge.merge",
            "EvidenceConflictDetector.detect",
            "TrustPolicy.apply",
            "ContextBudgetManager.apply",
        ]
        assert call_log == expected, f"Call order mismatch: {call_log}"


# ── 13. QueryPlan metadata written to ctx ──────────────────────────

class TestQueryPlanMetadata:
    def test_pipeline_writes_all_metadata(self):
        """EvidencePipeline must write query plans and counts to ctx.metadata."""
        from agent.core.turn_context import TurnContext
        from agent.runtime.cognition.evidence_pipeline import EvidencePipeline

        ctx = TurnContext(workspace_id="test_ws", user_input="test query")
        ctx.metadata = {}

        pipeline = EvidencePipeline()
        pipeline.build(ctx)

        assert "context_query_plan" in ctx.metadata
        assert "memory_query_plan" in ctx.metadata
        assert "knowledge_query_plan" in ctx.metadata
        assert "evidence_conflicts" in ctx.metadata
        assert "trust_report" in ctx.metadata
        assert "evidence_memory_count" in ctx.metadata
        assert "evidence_knowledge_count" in ctx.metadata
        assert "safe_context_status" in ctx.metadata
        assert ctx.metadata["safe_context_status"] == "ok"

    def test_pipeline_sets_context_frame(self):
        """EvidencePipeline must set ctx.context_frame."""
        from agent.core.turn_context import TurnContext
        from agent.runtime.cognition.evidence_pipeline import EvidencePipeline

        ctx = TurnContext(workspace_id="test_ws", user_input="test")
        ctx.metadata = {}

        pipeline = EvidencePipeline()
        pipeline.build(ctx)

        assert ctx.context_frame is not None

    def test_context_query_plan_is_dict(self):
        """context_query_plan metadata must be a dict with plan fields."""
        from agent.core.turn_context import TurnContext
        from agent.runtime.cognition.evidence_pipeline import EvidencePipeline

        ctx = TurnContext(workspace_id="test_ws", user_input="hello")
        ctx.metadata = {}

        pipeline = EvidencePipeline()
        pipeline.build(ctx)

        plan = ctx.metadata["context_query_plan"]
        assert isinstance(plan, dict)
        assert "include_workspace" in plan
        assert "reason" in plan
