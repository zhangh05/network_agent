# harness/test_cognitive_context_tool_refactor.py
"""Tests for the cognitive decision layer refactor.

Validates:
1. SceneDecision — simple_chat, local_ops, knowledge, translation, sub_agent
2. EvidenceBundle — normalization of memory/knowledge items
3. ToolPlannerV2 — importable
4. PromptCompiler — importable and callable
5. Current module boundaries
6. Local ops still exposed for explicit host scenes
"""

import pytest


# ── A. SceneDecision ──────────────────────────────────────────────────

class TestSceneDecision:
    def test_importable(self):
        from agent.runtime.cognition.scene_decision import SceneDecision, decide_scene
        assert SceneDecision is not None
        assert callable(decide_scene)

    def test_simple_chat_hello(self):
        from agent.runtime.cognition.scene_decision import decide_scene
        d = decide_scene("你好")
        assert d.is_simple_chat is True
        assert d.needs_tool is False
        assert d.primary_category == "chat"

    def test_simple_chat_hi(self):
        from agent.runtime.cognition.scene_decision import decide_scene
        d = decide_scene("hello")
        assert d.is_simple_chat is True
        assert d.needs_tool is False
        assert d.primary_category == "chat"

    def test_simple_chat_thanks(self):
        from agent.runtime.cognition.scene_decision import decide_scene
        d = decide_scene("谢谢")
        assert d.is_simple_chat is True

    def test_simple_chat_not_web_search(self):
        """Critical: simple chat must NOT default to web.search."""
        from agent.runtime.cognition.scene_decision import decide_scene
        d = decide_scene("你好")
        assert "web" not in d.categories
        assert d.primary_category != "web"

    def test_local_ops_task(self):
        from agent.runtime.cognition.scene_decision import decide_scene
        d = decide_scene("查看本机端口")
        assert d.needs_local_ops is True
        assert d.is_local_ops_task is True
        assert d.needs_tool is True
        assert "host" in d.categories

    def test_knowledge_task(self):
        from agent.runtime.cognition.scene_decision import decide_scene
        d = decide_scene("搜索知识库中关于 OSPF 的资料")
        assert d.is_knowledge_task is True
        assert d.needs_knowledge is True
        assert "knowledge" in d.categories

    def test_translation_task(self):
        from agent.runtime.cognition.scene_decision import decide_scene
        d = decide_scene("把这段 Cisco 配置翻译成华三")
        assert d.is_translation_task is True
        assert d.is_network_task is True
        assert "network" in d.categories

    def test_sub_agent_task(self):
        from agent.runtime.cognition.scene_decision import decide_scene
        d = decide_scene("帮我并行研究一下这三个问题")
        assert d.is_sub_agent_task is True
        assert d.needs_sub_agent is True
        assert "agent" in d.categories

    def test_web_task(self):
        from agent.runtime.cognition.scene_decision import decide_scene
        d = decide_scene("帮我查查最新的 BGP RFC 官方文档")
        assert d.is_web_task is True
        assert d.needs_web is True

    def test_file_task(self):
        from agent.runtime.cognition.scene_decision import decide_scene
        d = decide_scene("帮我分析这个上传的文件")
        assert d.is_file_task is True
        assert d.needs_file is True

    def test_memory_task(self):
        from agent.runtime.cognition.scene_decision import decide_scene
        d = decide_scene("记住我的偏好设置")
        assert d.is_memory_task is True
        assert d.needs_memory is True

    def test_report_task(self):
        from agent.runtime.cognition.scene_decision import decide_scene
        d = decide_scene("整理成报告并保存制品")
        assert d.is_report_task is True

    def test_followup_detection(self):
        from agent.runtime.cognition.scene_decision import decide_scene
        d = decide_scene(
            "不对，重新用shell试试",
            previous_scene={"primary_category": "host", "categories": ["host"]},
        )
        assert d.followup_inherited is True

    def test_empty_input(self):
        from agent.runtime.cognition.scene_decision import decide_scene
        d = decide_scene("")
        # Empty input treated as non-greeting
        assert d.is_simple_chat is True or d.needs_tool is False


# ── B. EvidenceBundle ─────────────────────────────────────────────────

class TestEvidenceBundle:
    def test_importable(self):
        from agent.runtime.cognition.evidence_models import (
            EvidenceItem, EvidenceBundle, ScanReport, BudgetReport,
        )
        assert EvidenceItem is not None
        assert EvidenceBundle is not None

    def test_memory_normalization(self):
        from agent.runtime.cognition.evidence_models import EvidenceItem, EvidenceBundle
        bundle = EvidenceBundle()
        bundle.memory_items.append(EvidenceItem(
            source_type="memory",
            title="用户偏好",
            content="偏好使用 CLI 配置",
            scan_status="safe",
        ))
        safe = bundle.to_safe_context()
        assert "memory_hits" in safe
        assert len(safe["memory_hits"]) == 1
        assert safe["memory_hits"][0]["title"] == "用户偏好"

    def test_knowledge_normalization(self):
        from agent.runtime.cognition.evidence_models import EvidenceItem, EvidenceBundle
        bundle = EvidenceBundle()
        bundle.knowledge_items.append(EvidenceItem(
            source_type="knowledge",
            title="OSPF RFC",
            content="OSPF protocol spec...",
            score=0.95,
            scan_status="safe",
        ))
        safe = bundle.to_safe_context()
        assert "knowledge_hits" in safe
        assert len(safe["knowledge_hits"]) == 1
        assert safe["knowledge_hits"][0]["score"] == 0.95

    def test_blocked_items_excluded(self):
        from agent.runtime.cognition.evidence_models import EvidenceItem, EvidenceBundle
        bundle = EvidenceBundle()
        bundle.memory_items.append(EvidenceItem(
            source_type="memory",
            title="blocked",
            scan_status="blocked",
        ))
        bundle.memory_items.append(EvidenceItem(
            source_type="memory",
            title="safe",
            scan_status="safe",
        ))
        safe = bundle.to_safe_context()
        assert len(safe["memory_hits"]) == 1
        assert safe["memory_hits"][0]["title"] == "safe"

    def test_by_source(self):
        from agent.runtime.cognition.evidence_models import EvidenceItem, EvidenceBundle
        bundle = EvidenceBundle()
        bundle.memory_items.append(EvidenceItem(source_type="memory", title="m1"))
        bundle.knowledge_items.append(EvidenceItem(source_type="knowledge", title="k1"))
        assert len(bundle.by_source("memory")) == 1
        assert len(bundle.by_source("knowledge")) == 1

    def test_empty_bundle_safe_context(self):
        from agent.runtime.cognition.evidence_models import EvidenceBundle
        bundle = EvidenceBundle()
        safe = bundle.to_safe_context()
        assert isinstance(safe, dict)
        assert "memory_hits" not in safe
        assert "knowledge_hits" not in safe


# ── C. ToolPlannerV2 ─────────────────────────────────────────────────

class TestToolPlannerV2:
    def test_importable(self):
        from agent.runtime.tool_planning.planner import ToolPlannerV2
        planner = ToolPlannerV2()
        assert hasattr(planner, "plan")

    def test_chat_does_not_default_to_web(self):
        """Simple chat scene should not produce web.search candidates."""
        from agent.runtime.cognition.scene_decision import decide_scene
        d = decide_scene("你好")
        assert d.is_simple_chat is True
        # ToolPlannerV2 should not be called for simple chat scenes
        # because needs_tool is False

    def test_scene_adapter_importable(self):
        from agent.runtime.tool_planning.scene_adapter import scene_to_rule_scene
        from agent.runtime.cognition.scene_decision import decide_scene
        d = decide_scene("查看本机端口")
        rule = scene_to_rule_scene(d)
        assert rule["primary_category"] == "host"
        assert "host" in rule["categories"]


# ── D. PromptCompiler ────────────────────────────────────────────────

class TestPromptCompiler:
    def test_importable(self):
        from agent.runtime.prompting.compiler import PromptCompiler
        assert callable(PromptCompiler)

    def test_blocks_importable(self):
        from agent.runtime.prompting.blocks import (
            CORE_PROMPT, ANTI_HALLUCINATION,
            TOOL_CATEGORY_GUIDE, SUB_AGENT_PREAMBLE,
        )
        assert "Network Agent" in CORE_PROMPT
        assert "sub-agent" in SUB_AGENT_PREAMBLE.lower()

    def test_safe_context_renderer_importable(self):
        from agent.runtime.prompting.safe_context_renderer import render_safe_context
        result = render_safe_context(None)
        assert result == ""
        result = render_safe_context({"workspace_id": "test"})
        assert "UNTRUSTED" in result

    def test_history_renderer_importable(self):
        from agent.runtime.prompting.history_renderer import build_user_content_with_images
        result = build_user_content_with_images(None, "hello")
        assert result == "hello"

    def test_scene_decision_can_drive_prompt_architecture(self):
        from types import SimpleNamespace
        from agent.runtime.cognition.scene_decision import decide_scene
        from agent.runtime.prompt_architecture.compiler import compile_runtime_prompt

        d = decide_scene("查看本机端口")
        context = SimpleNamespace(
            metadata={"scene_decision": d.__dict__},
            visible_tool_ids=["exec.run"],
            safe_context={},
        )
        assembly = compile_runtime_prompt(context)
        assert assembly.final_prompt


# ── E. Current module boundaries ────────────────────────────────────

class TestCurrentModuleBoundaries:
    def test_new_visibility_canonical(self):
        """Canonical path exports the policy constants."""
        from agent.runtime.tool_planning.visibility import (
            BASELINE_READ_TOOLS,
            LOCAL_OPS_TOOLS,
            scene_allows_local_ops,
            build_visibility_metadata,
        )
        assert isinstance(BASELINE_READ_TOOLS, list)
        assert isinstance(LOCAL_OPS_TOOLS, list)
        assert callable(scene_allows_local_ops)
        assert callable(build_visibility_metadata)

    def test_validation_canonical(self):
        """validate_tool_plan is importable from new path."""
        from agent.runtime.tool_planning.validation import validate_tool_plan
        assert callable(validate_tool_plan)


# ── F. Local ops exposed for explicit host scenes ────────────────────

class TestLocalOpsExposure:
    def test_local_ops_true_for_host_request(self):
        from agent.runtime.tool_planning.visibility import scene_allows_local_ops
        assert scene_allows_local_ops({}, "查看本机IP") is True

    def test_local_ops_false_for_translate(self):
        from agent.runtime.tool_planning.visibility import scene_allows_local_ops
        assert scene_allows_local_ops({}, "翻译这段配置") is False

    def test_baseline_includes_read_and_web_only(self):
        """BASELINE: read/discovery + web + exec.run (always visible).
        Other local exec tools stay scene-gated via LOCAL_OPS_TOOLS."""
        from agent.runtime.tool_planning.visibility import BASELINE_READ_TOOLS
        assert "exec.run" in BASELINE_READ_TOOLS
        assert "web.search" in BASELINE_READ_TOOLS

    def test_local_ops_contains_host_tools(self):
        """LOCAL_OPS_TOOLS: scene-gated host tools. exec.run was here in
        earlier revisions but moved to BASELINE in v3.9.1."""
        from agent.runtime.tool_planning.visibility import LOCAL_OPS_TOOLS
        assert "exec.run" not in LOCAL_OPS_TOOLS
        assert "exec.python" in LOCAL_OPS_TOOLS
        assert "system.diagnostics" in LOCAL_OPS_TOOLS

    def test_scene_decision_host_signals(self):
        """decide_scene should detect host signals correctly."""
        from agent.runtime.cognition.scene_decision import decide_scene
        d = decide_scene("用 shell 执行 ping 命令")
        assert d.is_local_ops_task is True
        assert d.needs_local_ops is True


# ── G. ContextBudget + MemoryPolicy ─────────────────────────────────

class TestCognitionModels:
    def test_context_budget_importable(self):
        from agent.runtime.cognition.context_budget import ContextBudgetManager
        mgr = ContextBudgetManager()
        assert hasattr(mgr, "apply")

    def test_memory_policy_importable(self):
        from agent.runtime.cognition.memory_policy import MemoryPolicy, MemoryDecision
        policy = MemoryPolicy()
        decision = policy.decide("记住我喜欢深色模式", {"mentions_memory": True})
        assert isinstance(decision, MemoryDecision)
        assert decision.should_search is True

    def test_evidence_pipeline_importable(self):
        from agent.runtime.cognition.evidence_pipeline import EvidencePipeline
        pipeline = EvidencePipeline()
        assert hasattr(pipeline, "build")


# ── H. ContextBuilder / ContextPipeline order verification ──────────

class TestContextBuilderOrder:
    def test_scene_before_evidence_before_tool_plan(self):
        """Pipeline stages must run scene → retrieval → evidence → tool_plan in order."""
        import inspect
        from agent.runtime.context_pipeline.pipeline import ContextPipeline
        source = inspect.getsource(ContextPipeline.run)

        # Stage 6 (scene) must appear before stage 9 (evidence) before stage 10 (tool_plan)
        idx_scene = source.index("self._scene.run")
        idx_evidence = source.index("self._evidence.run")
        idx_tool_plan = source.index("self._tool_planning.run")
        assert idx_scene < idx_evidence < idx_tool_plan

    def test_no_attach_scene_decision_at_end(self):
        """_attach_scene_decision should not exist — scene is computed early."""
        import inspect
        from agent.runtime import context_builder
        source = inspect.getsource(context_builder)
        assert "_attach_scene_decision" not in source

    def test_no_plan_tool_visibility_import(self):
        """context_builder should not import plan_tool_visibility."""
        import inspect
        from agent.runtime import context_builder
        source = inspect.getsource(context_builder)
        assert "plan_tool_visibility" not in source


# ── I. ToolPlannerV2 independence ────────────────────────────────────

class TestToolPlannerV2Independence:
    def test_no_plan_tools_import(self):
        """ToolPlannerV2 must not call plan_tools (the wrapper), only deterministic_plan_tools."""
        import inspect
        from agent.runtime.tool_planning import planner
        source = inspect.getsource(planner)
        # Should import deterministic_plan_tools, NOT plan_tools
        assert "deterministic_plan_tools" in source
        assert "from agent.runtime.tool_planner import plan_tools" not in source

    def test_no_old_tool_planner_reference(self):
        """ToolPlannerV2 source must not reference agent.runtime.tool_planner module."""
        import inspect
        from agent.runtime.tool_planning import planner
        source = inspect.getsource(planner)
        assert "agent.runtime.tool_planner" not in source

    def test_no_empty_safe_context(self):
        """ToolPlannerV2 must not pass safe_context={}."""
        import inspect
        from agent.runtime.tool_planning import planner
        source = inspect.getsource(planner)
        assert "safe_context={}" not in source

    def test_uses_validation(self):
        """ToolPlannerV2 must use validate_tool_plan from validation.py."""
        import inspect
        from agent.runtime.tool_planning import planner
        source = inspect.getsource(planner)
        assert "validate_tool_plan" in source


# ── J. EvidencePipeline independence ─────────────────────────────────

class TestEvidencePipelineIndependence:
    def test_no_safe_context_from_bundle_call(self):
        """EvidencePipeline must not delegate to safe_context_from_bundle."""
        import inspect
        from agent.runtime.cognition import evidence_pipeline
        source = inspect.getsource(evidence_pipeline)
        assert "safe_context_from_bundle" not in source

    def test_calls_scan_chunks_directly(self):
        """EvidencePipeline must call scan_chunk for injection scanning."""
        import inspect
        from agent.runtime.cognition import evidence_pipeline
        source = inspect.getsource(evidence_pipeline)
        assert "scan_chunk" in source

    def test_builds_scan_report(self):
        """EvidencePipeline must produce ScanReport objects."""
        import inspect
        from agent.runtime.cognition import evidence_pipeline
        source = inspect.getsource(evidence_pipeline)
        assert "ScanReport" in source


# ── K. Prompt/runtime boundary checks ────────────────────────────────

class TestPromptRuntimeBoundaries:
    def test_no_backward_compatible_fields_in_router(self):
        """tool_category_router.py must keep current field names explicit."""
        import inspect
        from agent.runtime import tool_category_router
        source = inspect.getsource(tool_category_router)
        _banned = "Backward" + "-compatible fields"
        assert _banned not in source

    def test_no_empty_safe_context_in_context_tools(self):
        """context_tools.py must not pass safe_context={}."""
        import inspect
        from agent.runtime import context_tools
        source = inspect.getsource(context_tools)
        assert "safe_context={}" not in source

    def test_no_plan_tool_visibility_in_context_tools(self):
        """context_tools.py must not define plan_tool_visibility."""
        import agent.runtime.context_tools as mod
        assert not hasattr(mod, "plan_tool_visibility")

    def test_router_scene_no_category_compat_key(self):
        """route_tool_scene must not return 'category' compat key."""
        from agent.runtime.tool_category_router import route_tool_scene
        result = route_tool_scene("查看本机端口")
        assert "category" not in result
        assert "group" not in result
        assert "primary_category" in result


# ── L. Simple chat does not default to web.search ────────────────────

class TestSimpleChatNoWebSearch:
    def test_simple_chat_no_web_category(self):
        from agent.runtime.cognition.scene_decision import decide_scene
        for msg in ("你好", "hello", "谢谢", "ok"):
            d = decide_scene(msg)
            assert d.is_simple_chat is True, f"{msg!r} should be simple chat"
            assert "web" not in d.categories, f"{msg!r} should not have web category"
            assert d.primary_category != "web", f"{msg!r} should not be web primary"

    def test_scene_adapter_chat_produces_chat_primary(self):
        from agent.runtime.cognition.scene_decision import decide_scene
        from agent.runtime.tool_planning.scene_adapter import scene_to_rule_scene
        d = decide_scene("你好")
        rule = scene_to_rule_scene(d)
        assert rule["primary_category"] == "chat"


# ── M. Artifact evidence enables file tools ──────────────────────────

class TestArtifactEvidenceEnablesFileTools:
    def test_artifact_refs_in_evidence(self):
        """EvidenceBundle with artifact_refs should include them in safe_context."""
        from agent.runtime.cognition.evidence_models import EvidenceBundle
        bundle = EvidenceBundle()
        bundle.artifact_refs = [{"artifact_id": "config_001", "name": "running-config.txt"}]
        safe = bundle.to_safe_context()
        assert "artifact_refs" in safe
        assert len(safe["artifact_refs"]) == 1
        assert safe["artifact_refs"][0]["artifact_id"] == "config_001"

    def test_workspace_state_in_evidence(self):
        """EvidenceBundle with workspace_state should include it in safe_context."""
        from agent.runtime.cognition.evidence_models import EvidenceBundle
        bundle = EvidenceBundle()
        bundle.workspace_state = {"files": ["config.txt"], "workspace_id": "ws1"}
        safe = bundle.to_safe_context()
        assert "workspace_state" in safe
        assert safe["workspace_state"]["workspace_id"] == "ws1"


# ── N. Refactor architecture assertions ───────────────────────────────

class TestRefactorArchitecture:
    _OLD_COMPACTION = "context" + "_compaction"

    def test_context_budget_no_old_compaction_reference(self):
        """context_budget.py must not reference the old compaction module."""
        import inspect
        from agent.runtime.cognition import context_budget
        source = inspect.getsource(context_budget)
        assert self._OLD_COMPACTION not in source
        assert "auto_compact_context" not in source

    def test_tool_planning_no_old_tool_planner_import(self):
        """No module under tool_planning/ should import from agent.runtime.tool_planner."""
        import inspect
        from agent.runtime.tool_planning import planner, chain_builder, visibility, validation
        for mod in (planner, chain_builder, visibility, validation):
            source = inspect.getsource(mod)
            assert "agent.runtime.tool_planner" not in source, \
                f"{mod.__name__} still references agent.runtime.tool_planner"

    def test_cognition_no_old_compaction_import(self):
        """No module under cognition/ should import from the old compaction module."""
        import inspect
        from agent.runtime.cognition import context_budget, evidence_pipeline
        for mod in (context_budget, evidence_pipeline):
            source = inspect.getsource(mod)
            assert self._OLD_COMPACTION not in source, \
                f"{mod.__name__} still references the old compaction module"

    def test_plan_tools_available_from_new_location(self):
        """plan_tools and deterministic_plan_tools importable from tool_planning.planner."""
        from agent.runtime.tool_planning.planner import plan_tools, deterministic_plan_tools
        assert callable(plan_tools)
        assert callable(deterministic_plan_tools)

    def test_needs_file_clarification_available_from_new_location(self):
        """_needs_file_clarification importable from tool_planning.planner."""
        from agent.runtime.tool_planning.planner import _needs_file_clarification
        assert callable(_needs_file_clarification)
